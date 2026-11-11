"""Only a reserved main build can publish, and retries never overwrite releases."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'build-support'), str(ROOT / 'build-support/update')]
import custom_release as publisher
import custom_release_versions as versions
import custom_feed
import feed
import release_assets
from test_custom_release_versions import GitHub, COMMIT, SOURCE, PREFIX


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.remote = GitHub()
        self.reservation = versions.reserve(COMMIT, SOURCE, '0.3.5', 100, self.remote.request)
        self.tag = self.reservation['tag']
        self.latest = COMMIT
        self.live = None
        self.env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'Natsuneko3/oink',
                    'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': COMMIT,
                    'GITHUB_RUN_ID': '100',
                    'GITHUB_WORKFLOW_REF': 'Natsuneko3/oink/.github/workflows/custom-release.yml@refs/heads/main'}
        identity = {**publisher.IDENTITY, 'version': '0.3.6'}
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, self.env, clear=True).start()
        patch.object(publisher, 'IDENTITY', identity).start()
        patch.object(publisher, 'head', return_value=COMMIT).start()
        patch.object(publisher, 'source_tree_sha256', return_value=SOURCE).start()
        patch.object(release_assets, 'request', side_effect=self.request).start()
        self.record = self.make_record(identity)
        (self.output / 'release.json').write_text(json.dumps(self.record))
        (self.output / 'SHA256SUMS').write_text('fixture')
        self.command = patch.object(publisher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)).start()

    def request(self, path, method='GET', payload=None, **kwargs):
        if path == PREFIX + '/git/ref/heads/main':
            return {'object': {'type': 'commit', 'sha': self.latest,
                               'url': f'https://api.github.com/{PREFIX}/git/commits/{self.latest}'}}
        if path == PREFIX + '/releases/tags/' + self.tag:
            return self.live
        return self.remote.request(path, method, payload, **kwargs)

    def asset(self, name):
        path = self.output / name; path.write_bytes(name.encode())
        return {'name': name, 'size': path.stat().st_size, 'sha256': publisher.digest(path)}

    def make_record(self, identity):
        platforms = {}
        for name, architecture in (('macos', 'arm64'), ('macos-x64', 'x64'), ('windows', 'x64')):
            record = {'schema': 1, 'product': 'Oink', 'version': '0.3.6', 'build': 117,
                      'source_tree_sha256': SOURCE, 'source_commit': None, 'architecture': architecture,
                      'protocol_baseline': 1, 'built_commit': COMMIT, 'custom_release': True}
            if name == 'windows':
                record.update(signing='unsigned', updater_included=True, collector_included=True,
                              artifacts=[self.asset('Oink-0.3.6-windows-x64.msi')])
            else:
                record.update(signing='apple-development', development_signing=True, notarized=False,
                              team_id=identity['macos']['team_id'], certificate_sha1=identity['macos']['signing_fingerprint'],
                              sparkle={'public_key_configured': True},
                              launch_smoke={'signed': True, 'status': 'passed', 'seconds': 10},
                              artifacts=[self.asset(f'Oink-0.3.6-macos-{architecture}.{suffix}') for suffix in ('dmg', 'zip')])
            platforms[name] = record
        return {'schema': 1, 'product': 'Oink', 'version': '0.3.6', 'build': 117,
                'built_commit': COMMIT, 'source_tree_sha256': SOURCE, 'custom_release': True,
                'platforms': platforms, 'artifacts': [a for p in platforms.values() for a in p['artifacts']],
                'source_artifact': self.asset('Oink-0.3.6-build117-source.tar.gz')}

    def test_reserved_push_publishes_plain_version_with_existing_signer(self):
        self.assertTrue(publisher.publish(self.output, self.tag, Path('notes.md')))
        argv = self.command.call_args.args[0]
        self.assertIn('--verify-tag', argv)
        self.assertIn('v0.3.6', argv)
        self.assertNotIn('custom', argv[argv.index('--title') + 1])
        self.assertTrue(all(str(self.output) in arg for arg in argv[-8:]))

    def test_superseded_commit_skips_upload_without_changing_the_release(self):
        self.latest = 'c' * 40
        self.assertFalse(publisher.publish(self.output, self.tag, Path('notes.md')))
        self.command.assert_not_called()

    def test_delayed_run_with_the_same_commit_cannot_replace_a_higher_published_build(self):
        self.remote.releases.append({'tag_name': 'v0.3.7', 'assets': [
            {'name': 'Oink-0.3.7-build118-source.tar.gz'}]})
        self.assertFalse(publisher.publish(self.output, self.tag, Path('notes.md')))
        self.command.assert_not_called()

    def test_another_release_cannot_reuse_this_build_number(self):
        self.remote.releases.append({'tag_name': 'v0.3.7', 'assets': [
            {'name': 'Oink-0.3.7-build117-source.tar.gz'}]})
        with self.assertRaisesRegex(ValueError, 'release_build_already_published'):
            publisher.publish(self.output, self.tag, Path('notes.md'))
        self.command.assert_not_called()

    def test_untrusted_events_repositories_and_refs_never_upload(self):
        for change in ({'GITHUB_EVENT_NAME': 'pull_request'}, {'GITHUB_REPOSITORY': 'attacker/oink'},
                       {'GITHUB_REF': 'refs/heads/other'}, {'GITHUB_ACTIONS': 'false'}):
            with self.subTest(change=change), patch.dict(os.environ, change), self.assertRaises(ValueError):
                publisher.publish(self.output, self.tag, Path('notes.md'))
        self.command.assert_not_called()

    def test_source_or_build_mismatch_with_reserved_tag_never_uploads(self):
        for key, value in (('build', 118), ('source_tree_sha256', 'd' * 64), ('version', '0.3.7')):
            altered = {**self.record, key: value}
            (self.output / 'release.json').write_text(json.dumps(altered))
            with self.subTest(key=key), self.assertRaises(ValueError):
                publisher.publish(self.output, self.tag, Path('notes.md'))
        self.command.assert_not_called()

    def test_modified_package_is_rejected_before_upload(self):
        (self.output / self.record['artifacts'][0]['name']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'final_asset_digest'):
            publisher.publish(self.output, self.tag, Path('notes.md'))
        self.command.assert_not_called()

    def existing(self, record=None):
        raw = json.dumps(record or self.record).encode()
        url = f'https://github.com/Natsuneko3/oink/releases/download/{self.tag}/release.json'
        self.live = {'tag_name': self.tag, 'draft': False, 'prerelease': False, 'published_at': '2026-11-11T00:00:00Z',
                     'assets': [{'name': 'release.json', 'size': len(raw), 'browser_download_url': url}]}
        return patch.object(feed, 'download', return_value=raw)

    def test_existing_matching_release_is_verified_without_overwriting_assets(self):
        with self.existing():
            self.assertTrue(publisher.publish(self.output, self.tag, Path('notes.md')))
        self.command.assert_not_called()

    def test_existing_release_with_different_provenance_is_rejected(self):
        with self.existing({**self.record, 'built_commit': 'c' * 40}), self.assertRaises(ValueError):
            publisher.publish(self.output, self.tag, Path('notes.md'))
        self.command.assert_not_called()


class FeedContextTests(unittest.TestCase):
    def test_push_and_manual_contexts_can_recover_but_other_events_cannot(self):
        context = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'Natsuneko3/oink',
                   'GITHUB_REF': 'refs/heads/main', 'OINK_FEED_LOCK': 'oink-update-feed-publish'}
        for event in ('push', 'workflow_dispatch', 'pull_request', 'release'):
            with self.subTest(event=event), patch.dict(os.environ, {**context, 'GITHUB_EVENT_NAME': event},clear=True), \
                    patch.object(sys, 'argv', ['custom_feed.py', '--recover']), patch.object(custom_feed, 'recover') as recover:
                if event in ('push', 'workflow_dispatch'):
                    custom_feed.main();recover.assert_called_once()
                else:
                    with self.assertRaisesRegex(ValueError, 'custom_feed_context'):
                        custom_feed.main()
                    recover.assert_not_called()


class FeedRetryTests(unittest.TestCase):
    def test_committed_release_is_read_back_instead_of_allocating_or_signing_again(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            tag = 'v0.3.6'
            record = {'build': 117, 'version': '0.3.6', 'source_tree_sha256': SOURCE, 'platforms': {}}
            catalog = {}
            for platform, path in (('macos', ''), ('macos-x64', 'x64/')):
                asset = {'name': platform + '.zip', 'sha256': 'c' * 64}
                record['platforms'][platform] = {'artifacts': [asset]}
                for channel in ('stable', 'beta'):
                    catalog[f'mac/v1/mac-2026-01/{path}{channel}/appcast.xml'] = {
                        'build': 117, 'version': '0.3.6', 'sha256': asset['sha256'],
                        'url': f'https://github.com/Natsuneko3/oink/releases/download/{tag}/{asset["name"]}'}
            asset = {'name': 'Oink-0.3.6-windows-x64.msi', 'sha256': 'd' * 64}
            record['platforms']['windows'] = {'artifacts': [asset]}
            approved = {'schema': 1, 'approved': True, 'published': True, 'source_tree_sha256': SOURCE,
                        'release': {'build': 117, 'version': '0.3.6', 'tag': tag,
                                    'package': {'sha256': asset['sha256'], 'url':
                                        f'https://github.com/Natsuneko3/oink/releases/download/{tag}/{asset["name"]}'}}}
            path = state / 'site/windows/releases/117/release.json';feed.write(path, approved)
            record_hash = feed.digest(path.read_bytes())
            registry = {'schema': 1, 'platforms': {'mac': {'enabled': True, 'catalog': catalog}, 'windows': {'enabled': True}},
                        'feeds': {'win-2026-01': {c: {'records': [record_hash]} for c in ('stable', 'beta')}}}
            feed.write(state / 'registry.json', registry)
            with patch.object(custom_feed.feed_site, 'verify_all') as verify, \
                    patch.object(custom_feed.feed_site, 'verify_public') as readback:
                self.assertTrue(custom_feed.already_published(state, record, tag))
                verify.assert_called_once_with(state);readback.assert_called_once_with(state)
                registry['feeds']['retired-epoch'] = {'stable': {'records': []}}
                feed.write(state / 'registry.json', registry)
                self.assertTrue(custom_feed.already_published(state, record, tag))
                registry['feeds']['win-2026-01']['beta']['records'] = []
                feed.write(state / 'registry.json', registry)
                self.assertFalse(custom_feed.already_published(state, record, tag))


if __name__ == '__main__':
    unittest.main()
