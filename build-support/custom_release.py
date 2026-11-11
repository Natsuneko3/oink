#!/usr/bin/env python3
"""Publish GitHub-built signed distributions with explicit provenance checks."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from identity import IDENTITY, valid_development_identity
from provenance import ROOT, digest, source_tree_sha256

REPOSITORY = 'Natsuneko3/oink'
PLATFORMS = {'macos': ('macos-arm64', 'arm64'),
             'macos-x64': ('macos-x64', 'x64'), 'windows': ('windows-x64', 'x64')}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def head():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def validate(record, platform, build, commit, source):
    require(record.get('schema') == 1 and record.get('product') == IDENTITY['name'] and
            record.get('version') == IDENTITY['version'] and record.get('build') == build and
            record.get('source_tree_sha256') == source and record.get('source_commit') is None and
            record.get('architecture') == PLATFORMS[platform][1] and
            record.get('protocol_baseline') == 1 and not record.get('update_test_feed') and
            not record.get('mac_update_test_feed'), 'package_identity_mismatch')
    require(re.fullmatch('[0-9a-f]{40}', commit) is not None, 'invalid_commit')
    if platform == 'windows':
        require(record.get('signing') == 'unsigned' and record.get('updater_included') is True and
                record.get('collector_included') is True and
                record.get('development_cross_compile', False) is False, 'windows_development_package_required')
        suffixes = ['.msi']
    else:
        smoke = record.get('launch_smoke', {})
        require(valid_development_identity(record) and record.get('notarized') is False and
                smoke.get('signed') is True and record.get('sparkle', {}).get('public_key_configured') is True,
                'explicit_unnotarized_development_package_required')
        cross_compile = record.get('development_cross_compile', False)
        require(type(cross_compile) is bool, 'invalid_development_cross_compile_mode')
        if cross_compile:
            native_tests = record.get('audio_plugin_native_tests', {})
            components = record.get('components', [])
            backend = [item for item in components if item.get('role') == 'backend']
            require(platform == 'macos' and record.get('build_host_system') == 'Darwin' and
                    record.get('build_host_architecture') == 'x86_64' and
                    record.get('target_architecture') == 'arm64' and
                    smoke.get('status') == 'not-run' and smoke.get('reason') == 'cross-compilation' and
                    type(smoke.get('seconds')) is int and smoke['seconds'] == 0 and
                    smoke.get('signing') == record.get('signing') and
                    native_tests == {'status': 'not-run', 'reason': 'cross-compilation',
                                     'tests': ['loopback', 'driver-identity']} and
                    record.get('audio_plugin_install_permissions') == {'status': 'passed'} and
                    components and all(item.get('architecture') == 'arm64' and
                                       item.get('signature_verified') is True for item in components) and
                    len(backend) == 1 and smoke.get('backend') == backend[0].get('path') and
                    smoke.get('backend_sha256') == backend[0].get('sha256') and
                    re.fullmatch('[0-9a-f]{64}', smoke.get('backend_sha256', '')) is not None,
                    'explicit_development_cross_compile_record_required')
        else:
            require(smoke.get('status') == 'passed' and smoke.get('seconds') == 10,
                    'signed_native_launch_smoke_required')
        suffixes = ['.dmg', '.zip']
    require(sorted(Path(a['name']).suffix for a in record['artifacts']) == suffixes,
            'unexpected_package_artifacts')


def copy_assets(record, directory, output):
    for asset in record['artifacts']:
        name = asset['name']
        require(re.fullmatch('[A-Za-z0-9_.-]+', name) is not None and name not in ('.', '..'),
                'invalid_asset_name')
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == asset['size'] and
                digest(path) == asset['sha256'], 'package_asset_digest')
        require(not (output / name).exists(), 'duplicate_package_asset')
        shutil.copy2(path, output / name)


def stage(packages, platform, build, commit, output):
    require(commit == head(), 'checkout_commit_mismatch')
    paths = list(packages.glob('*/' + PLATFORMS[platform][0] + '/release.json'))
    require(len(paths) == 1, 'expected_one_platform_record')
    path = paths[0]
    record = json.loads(path.read_text(encoding='utf-8-sig'))
    validate(record, platform, build, commit, source_tree_sha256())
    output.mkdir(parents=True, exist_ok=True)
    copy_assets(record, path.parent, output)
    record['built_commit'] = commit
    record['custom_release'] = True
    record['reporting'] = {'configured': False, 'report_sent': False,
                           'version': record['version'], 'build': build}
    write(output / f'release-{platform}.json', record)


def assemble(downloads, build, commit, output):
    require(commit == head(), 'checkout_commit_mismatch')
    source = source_tree_sha256()
    output.mkdir(parents=True, exist_ok=True)
    records, assets = {}, []
    for platform in PLATFORMS:
        paths = list(downloads.rglob(f'release-{platform}.json'))
        require(len(paths) == 1, 'all_three_platform_records_required')
        record = json.loads(paths[0].read_text(encoding='utf-8-sig'))
        validate(record, platform, build, commit, source)
        require(record.get('built_commit') == commit and record.get('custom_release') is True,
                'platform_commit_mismatch')
        copy_assets(record, paths[0].parent, output)
        records[platform] = record
        assets.extend(record['artifacts'])
    source_name = f'Oink-{IDENTITY["version"]}-build{build}-source.tar.gz'
    archive = output / source_name
    subprocess.run(['git', 'archive', '--format=tar.gz', '--prefix=Oink-source/',
                    '--output', str(archive), commit], cwd=ROOT, check=True)
    source_asset = {'name': source_name, 'size': archive.stat().st_size, 'sha256': digest(archive)}
    combined = {'schema': 1, 'product': IDENTITY['name'], 'version': IDENTITY['version'],
                'build': build, 'built_commit': commit, 'source_tree_sha256': source,
                'custom_release': True, 'distribution': 'development-unnotarized',
                'platforms': records, 'artifacts': assets, 'source_artifact': source_asset}
    write(output / 'release.json', combined)
    files = [output / a['name'] for a in assets] + [archive, output / 'release.json']
    (output / 'SHA256SUMS').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in files))


def publish(output, tag, notes):
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and
            os.environ.get('GITHUB_REPOSITORY') == REPOSITORY and
            os.environ.get('GITHUB_REF') == 'refs/heads/main' and
            os.environ.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch'), 'trusted_release_context_required')
    record = json.loads((output / 'release.json').read_bytes())
    require(record.get('custom_release') is True and record['built_commit'] == head() and
            record['source_tree_sha256'] == source_tree_sha256() and record['version'] == IDENTITY['version'],
            'release_source_mismatch')
    require(tag == 'v' + record['version'], 'invalid_release_tag')
    sys.path.insert(0, str(ROOT / 'build-support/update'))
    import release_assets
    from custom_release_versions import tag_reservation, latest_published_build
    latest = release_assets.request(f'repos/{REPOSITORY}/git/ref/heads/main')
    if latest['object'].get('type') != 'commit' or latest['object'].get('sha') != record['built_commit']:
        print('Main has advanced; this superseded build will not publish a Release or update feeds.')
        return False
    reservation = tag_reservation(tag, release_assets.request)
    require(reservation is not None and all(reservation[k] == record[k] for k in
            ('version', 'build', 'built_commit', 'source_tree_sha256')), 'release_reservation_mismatch')
    maximum = latest_published_build(release_assets.request)
    if maximum > record['build']:
        print('A higher build is already public; this older reservation will not replace it.')
        return False
    live = release_assets.request(f'repos/{REPOSITORY}/releases/tags/{tag}', missing=True)
    if live is not None:
        import feed
        require(live.get('tag_name') == tag and live.get('draft') is False and
                live.get('prerelease') is False and live.get('published_at'), 'existing_release_not_public')
        manifests = [a for a in live['assets'] if a['name'] == 'release.json']
        require(len(manifests) == 1 and 0 < manifests[0]['size'] <= feed.MAX_FEED and
                manifests[0]['browser_download_url'] ==
                f'https://github.com/{REPOSITORY}/releases/download/{tag}/release.json', 'existing_release_manifest')
        raw = feed.download(manifests[0]['browser_download_url'], feed.MAX_FEED, True)
        require(len(raw) == manifests[0]['size'], 'existing_release_manifest_size')
        existing = feed.loads(raw)
        require(all(existing.get(k) == record.get(k) for k in
                ('schema', 'product', 'version', 'build', 'built_commit', 'source_tree_sha256', 'custom_release')) and
                set(existing.get('platforms', {})) == set(PLATFORMS), 'existing_release_provenance')
        for platform, receipt in existing['platforms'].items():
            validate(receipt, platform, record['build'], record['built_commit'], record['source_tree_sha256'])
            require(receipt.get('built_commit') == record['built_commit'] and receipt.get('custom_release') is True,
                    'existing_platform_provenance')
        print('This reserved Release is already public with matching provenance; keeping its original assets.')
        return True
    require(maximum < record['build'], 'release_build_already_published')
    assets = record['artifacts'] + [record['source_artifact']]
    for asset in assets:
        path = output / asset['name']
        require(path.stat().st_size == asset['size'] and digest(path) == asset['sha256'], 'final_asset_digest')
    files = [output / a['name'] for a in assets] + [output / 'release.json', output / 'SHA256SUMS']
    subprocess.run(['gh', 'release', 'create', tag, '--repo', REPOSITORY,
                    '--verify-tag', '--target', record['built_commit'], '--latest', '--title', f'Oink {tag}',
                    '--notes-file', str(notes), *map(str, files)], cwd=ROOT, check=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['stage', 'assemble', 'publish'])
    parser.add_argument('--packages', type=Path)
    parser.add_argument('--platform', choices=PLATFORMS)
    parser.add_argument('--build', type=int)
    parser.add_argument('--commit', default=os.environ.get('GITHUB_SHA'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--downloads', type=Path)
    parser.add_argument('--tag')
    parser.add_argument('--notes', type=Path, default=Path('.github/custom-release-notes.md'))
    args = parser.parse_args()
    if args.operation == 'publish':
        published = publish(args.output, args.tag, args.notes)
        if os.environ.get('GITHUB_OUTPUT'):
            with Path(os.environ['GITHUB_OUTPUT']).open('a') as outputs:
                outputs.write(f'published={str(published).lower()}\n')
    else:
        require(type(args.build) is int and 113 < args.build < 2**31, 'custom_build_must_advance_113')
        if args.operation == 'stage':
            stage(args.packages, args.platform, args.build, args.commit, args.output)
        else:
            assemble(args.downloads, args.build, args.commit, args.output)


if __name__ == '__main__':
    main()
