"""Release hosting preserves verified snapshots and initializes forks safely."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'build-support/update'))
import feed
import feed_site
import release_assets as hosting


class ReleaseAssetsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / 'state'
        feed_site.initialize(self.state)
        self.assets = {}
        self.release = None
        self.branch = None
        self.tree = None
        self.commit = None
        self.api = patch.object(hosting, 'request', side_effect=self.request)
        self.api.start()
        self.addCleanup(self.api.stop)
        self.upload = patch.object(hosting, 'command', side_effect=self.command)
        self.upload.start()
        self.addCleanup(self.upload.stop)

    def request(self, path, method='GET', payload=None, missing=False):
        self.assertTrue(path.startswith('repos/Natsuneko3/oink/'), path)
        if path.endswith('/releases/tags/update-feed'):
            if self.release is None:
                self.assertTrue(missing)
                return None
            return copy.deepcopy(self.release)
        if path.endswith('/releases') and method == 'POST':
            self.release = {**payload, 'id': 7}
            return copy.deepcopy(self.release)
        if '/releases/7/assets?' in path:
            return [{'id': i, 'name': name} for i, name in enumerate(self.assets, 1)]
        if '/releases/assets/' in path and method == 'DELETE':
            del self.assets[list(self.assets)[int(path.rsplit('/', 1)[1]) - 1]]
            return None
        if path.endswith('/git/ref/heads/update-feed-state'):
            return self.branch
        if path.endswith('/git/trees'):
            self.tree = copy.deepcopy(payload['tree'])
            return {'sha': 'b' * 40}
        if path.endswith('/git/commits'):
            self.commit = copy.deepcopy(payload)
            return {'sha': 'c' * 40}
        if path.endswith('/git/refs'):
            self.branch = copy.deepcopy(payload)
            return self.branch
        self.fail('unexpected external API: ' + path)

    def command(self, argv, **kwargs):
        self.assertEqual(argv[:7], ['gh', 'release', 'upload', 'update-feed', '--repo', 'Natsuneko3/oink', '--clobber'])
        for path in map(Path, argv[7:]):
            self.assets[path.name] = path.read_bytes()
        return b''

    def test_first_publication_creates_prerelease_and_uploads_flat_asset_bytes(self):
        hosting.publish(self.state)
        self.assertEqual(self.assets, {'index.html': b'<!doctype html><title>Oink updates</title><p>Oink update feeds.</p>\n'})
        self.assertFalse(self.release['draft'])
        self.assertTrue(self.release['prerelease'])
        self.assertEqual(self.release['tag_name'], 'update-feed')

    def test_full_snapshot_removes_stale_managed_assets_but_keeps_unrelated_uploads(self):
        self.assets = {'windows-v1-win-2026-01-stable-manifest.json': b'failed candidate', 'user-notes.txt': b'keep'}
        hosting.publish(self.state)
        self.assertNotIn('windows-v1-win-2026-01-stable-manifest.json', self.assets)
        self.assertEqual(self.assets['user-notes.txt'], b'keep')
        self.assertEqual(self.assets['index.html'], (self.state / 'site/index.html').read_bytes())

    def test_bootstrap_refuses_to_reset_an_existing_live_snapshot(self):
        registry = feed.registry(self.state)
        registry['revision'] = 1
        feed.write(self.state / 'registry.json', registry)
        with self.assertRaisesRegex(ValueError, 'bootstrap_noninitial_state'):
            hosting.bootstrap(self.state)
        self.assertIsNone(self.release)
        self.assertEqual(self.assets, {})

    def test_bootstrap_does_not_reset_an_existing_feed_release(self):
        self.release = dict(id=7, tag_name='update-feed', draft=False, prerelease=True)
        self.assets = {'mac-v1-mac-2026-01-stable-appcast.xml': b'live feed'}
        with self.assertRaisesRegex(ValueError, 'bootstrap_release_not_empty'):
            hosting.bootstrap(self.state)
        self.assertEqual(self.assets, {'mac-v1-mac-2026-01-stable-appcast.xml': b'live feed'})

    def test_initialization_creates_only_disabled_orphan_state_and_preserves_existing_branch(self):
        hosting.initialize_state()
        self.assertEqual(self.branch['ref'], 'refs/heads/update-feed-state')
        self.assertEqual(self.commit['parents'], [])
        files = {entry['path']: entry['content'] for entry in self.tree}
        registry = json.loads(files['registry.json'])
        self.assertEqual(registry['revision'], 0)
        self.assertTrue(all(not slot['enabled'] for slot in registry['platforms'].values()))
        self.assertEqual(set(files), {'registry.json', 'site/index.html'})
        self.tree = None
        hosting.initialize_state()
        self.assertIsNone(self.tree, 'existing data branch must never be reinitialized')

    def test_rollback_uses_frozen_parent_even_when_local_commit_contains_candidate(self):
        subprocess.run(['git', 'init', str(self.state)], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(self.state), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.state), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'initial'], check=True, capture_output=True)
        head = subprocess.check_output(['git', '-C', str(self.state), 'rev-parse', 'HEAD']).decode().strip()
        fence = self.root / 'transaction.json'
        feed.write(fence, {'head': head, 'revision': 0})
        original = (self.state / 'site/index.html').read_bytes()
        (self.state / 'site/index.html').write_bytes(b'new candidate already copied by commit')
        hosting.rollback(self.state, fence)
        self.assertEqual(self.assets['index.html'], original)
        self.assertEqual((self.state / 'site/index.html').read_bytes(), b'new candidate already copied by commit')

    def test_unexpected_asset_paths_are_rejected_before_remote_changes(self):
        feed.write(self.state / 'site/unrelated/private.pem', b'never publish')
        with self.assertRaisesRegex(ValueError, 'release_asset_path'):
            hosting.publish(self.state)
        self.assertIsNone(self.release)


if __name__ == '__main__':
    unittest.main()
