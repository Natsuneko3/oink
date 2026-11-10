#!/usr/bin/env python3
"""Host verified update snapshots in this fork's dedicated prerelease.

Signing remains in the platform publishers. This boundary publishes exact bytes,
removes only stale managed feed assets, and can restore the frozen Git parent.
No code from the update-feed-state data branch is executed.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import feed
import feed_site

PREFIX = f'repos/{feed.REPOSITORY}'
STATE_BRANCH = 'update-feed-state'


def command(argv):
    result = subprocess.run(list(map(str, argv)), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    feed.require(result.returncode == 0, 'release_command_failed')
    return result.stdout


def request(path, method='GET', payload=None, missing=False):
    argv = ['gh', 'api', path, '--method', method, '--include']
    if payload is not None:
        argv += ['--input', '-']
    result = subprocess.run(argv, input=None if payload is None else feed.encode(payload),
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw = result.stdout.replace(b'\r\n', b'\n')
    header, separator, body = raw.partition(b'\n\n')
    status = re.match(rb'HTTP/\S+ ([0-9]{3})\b', header)
    feed.require(bool(separator and status), 'release_api_failed')
    code = int(status[1])
    if missing and code == 404:
        return None
    feed.require(result.returncode == 0 and 200 <= code < 300, 'release_api_failed')
    return json.loads(body) if body.strip() else None


def ensure_release():
    release = request(f'{PREFIX}/releases/tags/{feed.FEED_TAG}', missing=True)
    if release is None:
        payload = {'tag_name': feed.FEED_TAG, 'name': 'Oink custom update feed',
                   'body': 'Signed update metadata for Natsuneko3/oink. Installers are in versioned Releases.',
                   'draft': False, 'prerelease': True}
        if os.environ.get('GITHUB_SHA'):
            payload['target_commitish'] = os.environ['GITHUB_SHA']
        release = request(f'{PREFIX}/releases', 'POST', payload)
    feed.require(release.get('tag_name') == feed.FEED_TAG and release.get('draft') is False and
                 release.get('prerelease') is True and type(release.get('id')) is int,
                 'unexpected_feed_release')
    return release


def release_assets(release):
    assets = []
    page = 1
    while True:
        batch = request(f'{PREFIX}/releases/{release["id"]}/assets?per_page=100&page={page}')
        feed.require(type(batch) is list, 'release_assets')
        assets.extend(batch)
        if len(batch) < 100:
            return assets
        page += 1


def managed_asset(name):
    return (name in ('index.html', 'heartbeat.json') or
            re.fullmatch(r'mac-v1-mac-2026-01-(?:x64-)?(?:stable|beta)-appcast\.xml', name) is not None or
            re.fullmatch(r'windows-v1-win-2026-01-(?:stable|beta)-manifest\.json', name) is not None or
            re.fullmatch(r'windows-releases-[1-9][0-9]*-release\.json', name) is not None)


def snapshot_assets(state):
    feed_site.verify_all(state, signatures=False)
    result = {}
    for path, raw in feed_site.files(state / 'site').items():
        name = feed.asset_name(path)
        allowed = (path in ('index.html', 'heartbeat.json') or
                   re.fullmatch(r'mac/v1/mac-2026-01/(?:x64/)?(?:stable|beta)/appcast\.xml', path) or
                   re.fullmatch(r'windows/v1/win-2026-01/(?:stable|beta)/manifest\.json', path) or
                   re.fullmatch(r'windows/releases/[1-9][0-9]*/release\.json', path))
        feed.require(allowed and name not in result, 'release_asset_path')
        result[name] = raw
    feed.require(bool(result), 'empty_release_snapshot')
    return result


def publish(state):
    desired = snapshot_assets(state)
    release = ensure_release()
    previous = release_assets(release)
    with tempfile.TemporaryDirectory(prefix='oink-release-assets-') as folder:
        paths = []
        for name, raw in sorted(desired.items()):
            path = Path(folder) / name
            path.write_bytes(raw)
            paths.append(path)
        # A failed upload may leave a partial snapshot. The workflow always
        # restores its frozen parent and verifies canonical public bytes.
        command(['gh', 'release', 'upload', feed.FEED_TAG, '--repo', feed.REPOSITORY,
                 '--clobber', *paths])
    for asset in previous:
        if managed_asset(asset['name']) and asset['name'] not in desired:
            request(f'{PREFIX}/releases/assets/{asset["id"]}', 'DELETE')


def initialize_state():
    if request(f'{PREFIX}/git/ref/heads/{STATE_BRANCH}', missing=True) is not None:
        return
    with tempfile.TemporaryDirectory(prefix='oink-initial-feed-') as folder:
        initial = Path(folder) / 'state'
        feed_site.initialize(initial)
        tree = request(f'{PREFIX}/git/trees', 'POST', {'tree': [
            {'path': path, 'mode': '100644', 'type': 'blob', 'content': raw.decode()}
            for path, raw in sorted(feed_site.files(initial).items())]})
    commit = request(f'{PREFIX}/git/commits', 'POST', {
        'message': 'Initialize disabled custom update feed state', 'tree': tree['sha'], 'parents': []})
    # No force update: a concurrent bootstrap can fail, but cannot reset state.
    request(f'{PREFIX}/git/refs', 'POST', {'ref': f'refs/heads/{STATE_BRANCH}', 'sha': commit['sha']})


def bootstrap(state):
    with tempfile.TemporaryDirectory(prefix='oink-bootstrap-feed-') as folder:
        feed_site.bootstrap(state, Path(folder) / 'site')
    existing = request(f'{PREFIX}/releases/tags/{feed.FEED_TAG}', missing=True)
    if existing is not None:
        feed.require(all(not managed_asset(a['name']) or a['name'] == 'index.html'
                         for a in release_assets(existing)), 'bootstrap_release_not_empty')
    publish(state)
    feed_site.verify_public(state)


def rollback(state, fence_path=Path('transaction.json')):
    fence = feed.read(fence_path)
    feed.require(re.fullmatch('[0-9a-f]{40}', fence['head']) is not None, 'state_cas')
    with tempfile.TemporaryDirectory(prefix='oink-feed-rollback-') as folder:
        frozen = Path(folder) / 'state'
        names = subprocess.check_output(['git', '-C', str(state), 'ls-tree', '-r', '--name-only',
                                         fence['head'], '--', 'registry.json', 'site', 'records']).decode().splitlines()
        for name in names:
            # Preserve exact parent bytes even if deploy.commit has already
            # copied the candidate and created a newer local Git commit.
            raw = subprocess.check_output(['git', '-C', str(state), 'show', f'{fence["head"]}:{name}'])
            feed.write(frozen / name, raw)
        publish(frozen)


def authorized():
    event = feed.read(Path(os.environ['GITHUB_EVENT_PATH']))
    branch = event.get('repository', {}).get('default_branch')
    feed.require(os.environ.get('GITHUB_ACTIONS') == 'true' and
                 os.environ.get('GITHUB_REPOSITORY') == feed.REPOSITORY and branch and
                 os.environ.get('GITHUB_REF') == 'refs/heads/' + branch, 'release_context')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['initialize-state', 'bootstrap', 'publish', 'rollback'])
    parser.add_argument('--state', type=Path, default=Path('feed-state'))
    args = parser.parse_args()
    authorized()
    if args.command == 'initialize-state':
        initialize_state()
    else:
        {'bootstrap': bootstrap, 'publish': publish, 'rollback': rollback}[args.command](args.state)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = str(error) if type(error) is ValueError and re.fullmatch('[a-z_0-9]+', str(error)) else 'release_hosting_failed'
        raise SystemExit(code) from None
