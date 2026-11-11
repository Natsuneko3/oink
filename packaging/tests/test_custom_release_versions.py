"""Automatic releases keep ordering across failures, retries, and product versions."""
import copy
import hashlib
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'build-support'))
import custom_release_versions as versions

COMMIT = 'a' * 40
SOURCE = 'b' * 64
PREFIX = 'repos/Natsuneko3/oink'


class GitHub:
    def __init__(self):
        self.refs = {f'v0.3.5-custom.{n}': {'type': 'commit', 'sha': COMMIT} for n in (1, 2)}
        self.objects = {}
        self.releases = [{'tag_name': f'v0.3.5-custom.{n}', 'assets': [
            {'name': f'Oink-0.3.5-custom-{build}-source.tar.gz'}]} for n, build in ((1, 114), (2, 116))]
        self.writes = []

    def request(self, path, method='GET', payload=None, **kwargs):
        if method == 'GET':
            if path.startswith(PREFIX + '/tags?'):
                page = int(path.split('page=')[-1])
                return [{'name': name} for name in sorted(self.refs)][100 * (page - 1):100 * page]
            if path.startswith(PREFIX + '/releases?'):
                page = int(path.split('page=')[-1])
                return copy.deepcopy(self.releases[100 * (page - 1):100 * page])
            if path.startswith(PREFIX + '/git/ref/tags/'):
                return {'object': copy.deepcopy(self.refs[path.split('/tags/', 1)[1]])}
            if path.startswith(PREFIX + '/git/tags/'):
                result = copy.deepcopy(self.objects[path.rsplit('/', 1)[1]])
                result['object']['url'] = f'https://api.github.com/{PREFIX}/git/commits/{result["object"]["sha"]}'
                return result
        self.writes.append((path, method, copy.deepcopy(payload)))
        if path == PREFIX + '/git/tags' and method == 'POST':
            sha = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            self.objects[sha] = {**payload, 'sha': sha, 'object': {'type': payload['type'], 'sha': payload['object']}}
            return {'sha': sha}
        if path == PREFIX + '/git/refs' and method == 'POST':
            name = payload['ref'].removeprefix('refs/tags/')
            if name in self.refs:
                raise ValueError('release_api_failed')
            self.refs[name] = {'type': 'tag', 'sha': payload['sha']}
            return {'ref': payload['ref']}
        raise AssertionError((path, method, payload))


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.remote = GitHub()

    def reserve(self, run=100, commit=COMMIT, source=SOURCE, version='0.3.5'):
        return versions.reserve(commit, source, version, run, self.remote.request)

    def test_next_identifiers_advance_from_the_real_published_baseline(self):
        selected = self.reserve()
        self.assertEqual((selected['build'], selected['version'], selected['tag']), (117, '0.3.6', 'v0.3.6'))
        annotation = self.remote.objects[self.remote.refs[selected['tag']]['sha']]
        self.assertEqual(annotation['object'], {'type': 'commit', 'sha': COMMIT})
        self.assertEqual(json.loads(annotation['message']), selected)
        self.assertTrue(all(method == 'POST' for _, method, _ in self.remote.writes))

    def test_a_failed_build_keeps_its_reservation_and_the_next_run_advances(self):
        first = self.reserve()
        second = self.reserve(101)
        self.assertEqual((first['build'], second['build']), (117, 118))
        self.assertEqual(second['tag'], 'v0.3.7')

    def test_same_run_reuses_its_reservation_without_writing_again(self):
        first = self.reserve()
        writes = copy.deepcopy(self.remote.writes)
        self.assertEqual(self.reserve(), first)
        self.assertEqual(self.remote.writes, writes)

    def test_retry_cannot_change_source_commit_hash_or_product_version(self):
        self.reserve()
        for change in ({'commit': 'c' * 40}, {'source': 'd' * 64}, {'version': '0.3.6'}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'reservation_source_mismatch'):
                self.reserve(**change)

    def test_new_source_version_sets_a_floor_without_resetting_numeric_build(self):
        self.reserve()
        next_version = self.reserve(101, version='0.4.0')
        self.assertEqual((next_version['build'], next_version['tag']), (118, 'v0.4.0'))

    def test_unpublished_plain_tag_still_reserves_its_version(self):
        self.remote.refs['v0.3.9'] = {'type': 'commit', 'sha': COMMIT}
        self.assertEqual(self.reserve()['tag'], 'v0.3.10')

    def test_release_and_tag_history_are_paginated(self):
        self.remote.releases = [{'tag_name': 'update-feed', 'assets': []}] * 100 + [
            {'tag_name': 'v0.3.12', 'assets': [{'name': 'Oink-0.3.12-build200-source.tar.gz'}]}]
        for n in range(100):
            self.remote.refs[f'unrelated-{n}'] = {'type': 'commit', 'sha': COMMIT}
        selected = self.reserve()
        self.assertEqual((selected['build'], selected['tag']), (201, 'v0.3.13'))

    def test_bad_reserved_metadata_fails_without_creating_another_tag(self):
        selected = self.reserve()
        annotation = self.remote.objects[self.remote.refs[selected['tag']]['sha']]
        annotation['message'] = json.dumps({**selected, 'build': True})
        writes = copy.deepcopy(self.remote.writes)
        with self.assertRaisesRegex(ValueError, 'invalid_release_reservation'):
            self.reserve(101)
        self.assertEqual(self.remote.writes, writes)

    def test_build_overflow_and_invalid_source_inputs_fail_before_writes(self):
        self.remote.releases[1]['assets'][0]['name'] = 'Oink-0.3.5-custom-2147483647-source.tar.gz'
        with self.assertRaisesRegex(ValueError, 'release_build_exhausted'):
            self.reserve()
        for change in ({'commit': 'short'}, {'source': 'z' * 64}, {'version': '0.3.5\nunsafe'}, {'run': True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.reserve(**change)
        self.assertEqual(self.remote.writes, [])


class ContextTests(unittest.TestCase):
    def test_only_this_repository_main_push_and_manual_workflow_can_allocate(self):
        context = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'Natsuneko3/oink',
                   'GITHUB_REF': 'refs/heads/main', 'GITHUB_EVENT_NAME': 'push',
                   'GITHUB_WORKFLOW_REF': 'Natsuneko3/oink/.github/workflows/custom-release.yml@refs/heads/main',
                   'GITHUB_SHA': COMMIT, 'GITHUB_RUN_ID': '100'}
        for event in ('push', 'workflow_dispatch'):
            self.assertEqual(versions.trusted_context({**context, 'GITHUB_EVENT_NAME': event}), (COMMIT, 100))
        for change in ({'GITHUB_ACTIONS': 'false'}, {'GITHUB_REPOSITORY': 'attacker/oink'},
                       {'GITHUB_REF': 'refs/tags/v0.3.5'}, {'GITHUB_EVENT_NAME': 'pull_request'},
                       {'GITHUB_WORKFLOW_REF': 'Natsuneko3/oink/.github/workflows/other.yml@refs/heads/main'},
                       {'GITHUB_SHA': 'bad'}, {'GITHUB_RUN_ID': 'bad'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                versions.trusted_context({**context, **change})


if __name__ == '__main__':
    unittest.main()
