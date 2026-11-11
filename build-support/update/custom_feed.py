#!/usr/bin/env python3
"""Verify a signed fork Release and publish its macOS and Windows update feeds."""
import argparse
import copy
import io
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

import deploy
import feed
import feed_site
import mac_release
import release
import release_assets

sys.path.insert(0, str(feed.ROOT / 'build-support'))
from identity import IDENTITY, valid_development_identity
from provenance import source_tree_sha256
from sparkle import prepare


def command(args):
    result = subprocess.run(list(map(str, args)), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    feed.require(result.returncode == 0, 'custom_feed_command_failed')
    return result.stdout


def current_source():
    commit = command(['git', 'rev-parse', 'HEAD']).decode().strip()
    command(['git', 'diff', '--quiet', 'HEAD', '--'])
    # The nested data checkout is deliberately outside the product source hash.
    with tempfile.TemporaryDirectory(prefix='oink-feed-source-') as folder:
        with tarfile.open(fileobj=io.BytesIO(command(['git', 'archive', commit]))) as archive:
            archive.extractall(folder, filter='data')
        source = source_tree_sha256(Path(folder))
    return commit, source


def published(tag, commit, source):
    prefix = f'repos/{feed.REPOSITORY}'
    live = release_assets.request(f'{prefix}/releases/tags/{tag}')
    feed.require(live.get('draft') is False and live.get('prerelease') is False and
                 live.get('published_at') and live.get('tag_name') == tag, 'custom_release_not_public')
    reference = release_assets.request(f'{prefix}/git/ref/tags/{tag}')['object']
    for _ in range(4):
        if reference['type'] == 'commit':
            break
        feed.require(reference['type'] == 'tag', 'custom_tag_type')
        reference = release_assets.request(f'{prefix}/git/tags/{reference["sha"]}')['object']
    feed.require(reference['type'] == 'commit' and reference['sha'] == commit, 'custom_tag_commit')
    assets = {asset['name']: asset for asset in live['assets']}

    def download(name, limit):
        feed.require(re.fullmatch('[A-Za-z0-9_.-]+', name) is not None and name in assets, 'custom_asset_name')
        asset = assets[name]
        url = f'https://github.com/{feed.REPOSITORY}/releases/download/{tag}/{name}'
        feed.require(asset['browser_download_url'] == url and 0 < asset['size'] <= limit, 'custom_asset_url')
        raw = feed.download(url, limit, True)
        feed.require(len(raw) == asset['size'], 'custom_asset_size')
        return raw

    record = feed.loads(download('release.json', feed.MAX_FEED))
    feed.require(record.get('schema') == 1 and record.get('custom_release') is True and
                 record.get('product') == 'Oink' and record.get('version') == IDENTITY['version'] and
                 record.get('built_commit') == commit and record.get('source_tree_sha256') == source and
                 type(record.get('build')) is int and 0 < record['build'] < 2**31 and
                 set(record['platforms']) == {'macos', 'macos-x64', 'windows'}, 'custom_release_provenance')

    def package(asset):
        feed.require(asset in record['artifacts'], 'custom_artifact_membership')
        raw = download(asset['name'], feed.MAX_PACKAGE)
        feed.require(len(raw) == asset['size'] and feed.digest(raw) == asset['sha256'], 'custom_asset_digest')
        return raw

    return record, package


def windows_candidate(state, work, candidate, record, package, config, now):
    shutil.copytree(state, work, ignore=shutil.ignore_patterns('.git'))
    platform = record['platforms']['windows']
    feed.require(platform['built_commit'] == record['built_commit'] and
                 platform['build'] == record['build'] and platform['version'] == record['version'] and
                 platform['source_tree_sha256'] == record['source_tree_sha256'], 'windows_source_mismatch')
    with tempfile.TemporaryDirectory(prefix='oink-custom-msi-') as folder:
        inputs = Path(folder)
        feed.write(inputs / 'release.json', platform)
        feed.require(len(platform['artifacts']) == 1, 'windows_asset_count')
        asset = platform['artifacts'][0]
        feed.write(inputs / asset['name'], package(asset))
        approved = inputs / 'approved.json'
        release.sign_package(config, inputs, approved)
        release.register(config, work, approved, now)
    # Commit reservations and approved records BEFORE signing their sequences.
    # Do not copy uncommitted site files into the still-disabled real snapshot.
    for name in ('registry.json', 'pending-renewal.json'):
        feed.write(state / name, (work / name).read_bytes())
    shutil.copytree(work / 'records', state / 'records', dirs_exist_ok=True)
    command([sys.executable, feed.ROOT / 'build-support/update/reserve.py'])
    feed.write(work / 'registry.json', (state / 'registry.json').read_bytes())
    feed.sign_plans(work, config)
    feed_site.candidate(work, 'windows', candidate)


def mac_candidate(state, work, candidate, record, package, tag, cache):
    config = feed.trust('mac')
    feed.require(config['mac'].get('allow_development_updates') is True, 'development_updates_not_enabled')
    shutil.copytree(state, work, ignore=shutil.ignore_patterns('.git'))
    catalog = copy.deepcopy(feed.registry(state)['platforms']['mac'].get('catalog', {}))
    notes = feed.read(feed.ROOT / '.github/update-notes.json')['notes']
    feed.validate_notes(notes)
    signer = prepare(cache) / 'bin/sign_update'
    for platform, architecture, arch_path in (('macos', 'arm64', ''), ('macos-x64', 'x64', 'x64/')):
        metadata = record['platforms'][platform]
        feed.require(valid_development_identity(metadata) and metadata.get('notarized') is False and
                     metadata['built_commit'] == record['built_commit'] and
                     metadata['source_tree_sha256'] == record['source_tree_sha256'] and
                     metadata['build'] == record['build'] and metadata['version'] == record['version'] and
                     metadata['architecture'] == architecture, 'mac_development_provenance')
        archives = [asset for asset in metadata['artifacts'] if asset['name'].endswith('.zip')]
        feed.require(len(archives) == 1, 'mac_archive_count')
        asset = archives[0]
        with tempfile.TemporaryDirectory(prefix='oink-custom-mac-') as folder:
            folder = Path(folder)
            archive = folder / asset['name']
            feed.write(archive, package(asset))
            with zipfile.ZipFile(archive) as compressed:
                members = compressed.infolist()
                feed.require(sum(item.file_size for item in members) <= 1024 * 1024 * 1024 and
                             len(members) < 100000, 'mac_archive_limit')
                feed.require(all(not Path(item.filename).is_absolute() and '..' not in Path(item.filename).parts
                                 and '\\' not in item.filename for item in members), 'mac_archive_path')
                info = plistlib.loads(compressed.read('Oink.app/Contents/Info.plist'))
            feed.require(info.get('CFBundleIdentifier') == 'com.hachiwii.oink' and
                         info.get('CFBundleVersion') == str(record['build']) and
                         info.get('CFBundleShortVersionString') == record['version'] and
                         info.get('SUPublicEDKey') == config['mac']['public_key'], 'mac_bundle_identity')
            staging = folder / 'staging'
            command(['ditto', '-x', '-k', archive, staging])
            app = staging / 'Oink.app'
            command(['codesign', '--verify', '--strict', '--deep', app])
            if metadata['signing'] == 'apple-development':
                sys.path.insert(0, str(feed.ROOT / 'packaging/macos'))
                from signing import verify_signature
                for binary in app.rglob('*'):
                    if binary.is_file() and not binary.is_symlink():
                        with binary.open('rb') as header:
                            magic = header.read(4)
                        if magic in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
                            verify_signature(binary, IDENTITY['macos']['team_id'], apple_development=True,
                                             fingerprint=IDENTITY['macos']['signing_fingerprint'])
                verify_signature(app, IDENTITY['macos']['team_id'], apple_development=True,
                                 fingerprint=IDENTITY['macos']['signing_fingerprint'])
            native_arch = 'arm64' if architecture == 'arm64' else 'x86_64'
            arches = command(['lipo', '-archs', app / 'Contents/MacOS/oink-backend']).decode().split()
            feed.require(arches == [native_arch], 'mac_archive_architecture')
            signature = mac_release.sign(signer, archive, config['mac']['public_key'])
            publication = {'architecture': architecture, 'build': record['build'], 'version': record['version'],
                           'url': f'https://github.com/{feed.REPOSITORY}/releases/download/{tag}/{asset["name"]}',
                           'length': asset['size'], 'sha256': asset['sha256'],
                           'developer_id_verified': False, 'notarized': False, 'development_signing': True,
                           'code_signature_verified': True, 'qualified_build': None,
                           'published_build': record['build'], 'signing': metadata['signing'],
                           'team_id': metadata.get('team_id'), 'certificate_sha1': metadata.get('certificate_sha1')}
            for channel in ('stable', 'beta'):
                relative = f'mac/v1/{config["mac"]["epoch"]}/{arch_path}{channel}/appcast.xml'
                previous = catalog.get(relative)
                feed.require(previous is None or record['build'] > previous['build'], 'mac_release_not_monotonic')
                path = work / 'site' / relative
                mac_release.write_appcast(path, path.read_bytes() if path.exists() else None,
                                          publication, signature, notes)
                mac_release.sign(signer, path, config['mac']['public_key'], xml=True)
                catalog[relative] = publication
    catalog_path = work / 'catalog.json'
    feed.write(catalog_path, catalog)
    feed_site.candidate(work, 'mac', candidate, catalog_path)


def recover():
    fence_path = Path('transaction.json')
    if not fence_path.exists():
        return
    fence = feed.read(fence_path)
    remote = deploy.git('ls-remote', 'origin', 'refs/heads/update-feed-state').split()[0]
    local = deploy.git('rev-parse', 'HEAD')
    if remote == local and local != fence['head']:
        print('Update state commit was accepted; hosted feeds are retained.')
        return
    feed.require(remote == fence['head'], 'feed_recovery_state_changed')
    release_assets.rollback(Path('feed-state'))
    deploy.verify_rollback()


def already_published(state, record, tag):
    """A retry may follow a successful commit whose final acknowledgement was lost."""
    registry = feed.registry(state)
    if not all(registry['platforms'][platform]['enabled'] for platform in ('mac', 'windows')):
        return False
    catalog = registry['platforms']['mac'].get('catalog', {})
    for platform, arch_path in (('macos', ''), ('macos-x64', 'x64/')):
        archives = [a for a in record['platforms'][platform]['artifacts'] if a['name'].endswith('.zip')]
        feed.require(len(archives) == 1, 'mac_archive_count')
        asset = archives[0]
        expected = {'build': record['build'], 'version': record['version'], 'sha256': asset['sha256'],
                    'url': f'https://github.com/{feed.REPOSITORY}/releases/download/{tag}/{asset["name"]}'}
        for channel in ('stable', 'beta'):
            previous = catalog.get(f'mac/v1/mac-2026-01/{arch_path}{channel}/appcast.xml', {})
            if any(previous.get(k) != v for k, v in expected.items()):
                return False
    path = state / f'site/windows/releases/{record["build"]}/release.json'
    if not path.is_file():
        return False
    raw = path.read_bytes()
    approved = feed.loads(raw)
    asset = record['platforms']['windows']['artifacts'][0]
    expected = approved.get('release', {})
    if (approved.get('source_tree_sha256') != record['source_tree_sha256'] or
            expected.get('build') != record['build'] or expected.get('version') != record['version'] or
            expected.get('tag') != tag or expected.get('package', {}).get('sha256') != asset['sha256'] or
            expected.get('package', {}).get('url') !=
            f'https://github.com/{feed.REPOSITORY}/releases/download/{tag}/{asset["name"]}'):
        return False
    record_hash = feed.digest(raw)
    active = feed.trust()['windows']
    if not active or not all(record_hash in registry['feeds'].get(epoch['epoch'], {}).get(channel, {}).get('records', [])
                             for epoch in active for channel in epoch['channels']):
        return False
    # Keep the existing signature and public readback boundary even for a no-op retry.
    feed_site.verify_all(state)
    feed_site.verify_public(state)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-tag')
    parser.add_argument('--tool-cache', type=Path)
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    feed.require(os.environ.get('GITHUB_ACTIONS') == 'true' and
                 os.environ.get('GITHUB_REPOSITORY') == feed.REPOSITORY and
                 os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch') and
                 os.environ.get('GITHUB_REF') == 'refs/heads/main' and
                 os.environ.get('OINK_FEED_LOCK') == 'oink-update-feed-publish', 'custom_feed_context')
    if args.recover:
        recover()
        return
    feed.require(args.release_tag and args.tool_cache, 'custom_feed_arguments')
    feed.require(args.release_tag == 'v' + IDENTITY['version'], 'release_tag_version')
    commit, source = current_source()
    record, package = published(args.release_tag, commit, source)
    os.environ.update(OINK_SOURCE_TREE_SHA256=source, OINK_RELEASE_TAG=args.release_tag,
                      OINK_PUBLISHED_BUILD=str(record['build']))
    state, final = Path('feed-state'), Path('next-state')
    if already_published(state, record, args.release_tag):
        print('This Release already has verified public macOS and Windows update feeds.')
        return
    feed.require(not final.exists(), 'candidate_directory_exists')
    now = int(feed.dt.datetime.now(feed.dt.timezone.utc).timestamp())
    with tempfile.TemporaryDirectory(prefix='oink-custom-feeds-') as folder:
        folder = Path(folder)
        windows, mac = folder / 'windows-candidate', folder / 'mac-candidate'
        windows_candidate(state, folder / 'windows-work', windows, record, package, feed.trust(), now)
        mac_candidate(state, folder / 'mac-work', mac, record, package, args.release_tag, args.tool_cache)
        revision = feed.registry(state)['revision']
        merged_windows = folder / 'merged-windows'
        feed_site.merge(state, windows, merged_windows, revision)
        feed_site.merge(merged_windows, mac, final, revision + 1)
        fence = {'head': deploy.git('rev-parse', 'HEAD'), 'revision': revision}
        feed.write(Path('transaction.json'), fence)
        try:
            release_assets.publish(final)
            deploy.commit()
        except BaseException:
            recover()
            raise
    print('Published signed custom macOS and Windows update feeds.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        code = str(error) if type(error) is ValueError and re.fullmatch('[a-z_0-9]+', str(error)) else 'custom_feed_failed'
        raise SystemExit(code) from None
