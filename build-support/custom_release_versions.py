#!/usr/bin/env python3
"""Reserve monotonically ordered fork releases without changing product sources."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from identity import IDENTITY
from provenance import ROOT, source_tree_sha256

REPOSITORY = 'Natsuneko3/oink'
PREFIX = f'repos/{REPOSITORY}'
KIND = 'oink-custom-release-reservation-v1'
VERSION = r'[0-9]+\.[0-9]+\.[0-9]+(?:-beta\.[0-9]+)?'
TAG = re.compile(rf'v({VERSION})-custom\.([1-9][0-9]*)')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def trusted_context(environment=None):
    env = os.environ if environment is None else environment
    require(env.get('GITHUB_ACTIONS') == 'true' and env.get('GITHUB_REPOSITORY') == REPOSITORY and
            env.get('GITHUB_REF') == 'refs/heads/main' and
            env.get('GITHUB_EVENT_NAME') in ('push', 'workflow_dispatch') and
            env.get('GITHUB_WORKFLOW_REF') ==
            f'{REPOSITORY}/.github/workflows/custom-release.yml@refs/heads/main', 'trusted_release_context_required')
    commit, run_id = env.get('GITHUB_SHA', ''), env.get('GITHUB_RUN_ID', '')
    require(re.fullmatch('[0-9a-f]{40}', commit) and re.fullmatch('[1-9][0-9]*', run_id),
            'invalid_release_run_identity')
    return commit, int(run_id)


def pages(resource, request):
    page = 1
    while True:
        batch = request(f'{PREFIX}/{resource}?per_page=100&page={page}')
        require(type(batch) is list, 'invalid_release_history')
        yield from batch
        if len(batch) < 100:
            return
        page += 1


def annotation_reservation(annotation, tag):
    try:
        record = json.loads(annotation.get('message', ''))
    except (ValueError, TypeError):
        return None
    if not isinstance(record, dict) or record.get('kind') != KIND:
        return None
    match = TAG.fullmatch(tag)
    require(record.get('schema') == 1 and match and record.get('tag') == tag and
            annotation.get('tag') == tag and record.get('version') == match[1] and
            type(record.get('build')) is int and 113 < record['build'] < 2**31 and
            type(record.get('workflow_run_id')) is int and record['workflow_run_id'] > 0 and
            re.fullmatch('[0-9a-f]{40}', record.get('built_commit', '')) and
            re.fullmatch('[0-9a-f]{64}', record.get('source_tree_sha256', '')) and
            annotation.get('object') == {'type': 'commit', 'sha': record['built_commit']},
            'invalid_release_reservation')
    return record


def tag_reservation(tag, request):
    reference = request(f'{PREFIX}/git/ref/tags/{tag}', missing=True)
    if reference is None or reference['object']['type'] != 'tag':
        return None
    annotation = request(f'{PREFIX}/git/tags/{reference["object"]["sha"]}')
    return annotation_reservation(annotation, tag)


def reserve(commit, source, version, run_id, request):
    require(isinstance(commit, str) and re.fullmatch('[0-9a-f]{40}', commit) and
            isinstance(source, str) and re.fullmatch('[0-9a-f]{64}', source) and
            isinstance(version, str) and re.fullmatch(VERSION, version) and
            type(run_id) is int and run_id > 0, 'invalid_release_allocation_input')
    maximum, suffix, allocations = 113, 0, []
    builds, runs = set(), set()
    for item in pages('tags', request):
        tag = item['name']
        match = TAG.fullmatch(tag)
        if not match:
            continue
        if match[1] == version:
            suffix = max(suffix, int(match[2]))
        allocation = tag_reservation(tag, request)
        if allocation is not None:
            require(allocation['build'] not in builds and allocation['workflow_run_id'] not in runs,
                    'duplicate_release_reservation')
            builds.add(allocation['build'])
            runs.add(allocation['workflow_run_id'])
            maximum = max(maximum, allocation['build'])
            allocations.append(allocation)
    for release in pages('releases', request):
        match = TAG.fullmatch(release.get('tag_name', ''))
        if not match:
            continue
        if match[1] == version:
            suffix = max(suffix, int(match[2]))
        for asset in release.get('assets', []):
            name = re.fullmatch(re.escape(f'{IDENTITY["name"]}-{match[1]}-custom-') +
                                r'([1-9][0-9]*)-source\.tar\.gz', asset.get('name', ''))
            if name:
                maximum = max(maximum, int(name[1]))
    for allocation in allocations:
        if allocation['workflow_run_id'] == run_id:
            require((allocation['built_commit'], allocation['source_tree_sha256'], allocation['version']) ==
                    (commit, source, version), 'reservation_source_mismatch')
            return allocation
    require(maximum + 1 < 2**31, 'release_build_exhausted')
    tag = f'v{version}-custom.{suffix + 1}'
    record = {'schema': 1, 'kind': KIND, 'version': version, 'tag': tag, 'build': maximum + 1,
              'built_commit': commit, 'source_tree_sha256': source, 'workflow_run_id': run_id}
    annotation = request(f'{PREFIX}/git/tags', 'POST', {
        'tag': tag, 'message': json.dumps(record, sort_keys=True), 'object': commit, 'type': 'commit'})
    require(re.fullmatch('[0-9a-f]{40}', annotation.get('sha', '')), 'invalid_reserved_tag_object')
    # Never force a reference. A conflicting writer fails without recycling or replacing its tag.
    request(f'{PREFIX}/git/refs', 'POST', {'ref': f'refs/tags/{tag}', 'sha': annotation['sha']})
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    commit, run_id = trusted_context()
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    require(actual == commit, 'release_checkout_mismatch')
    sys.path.insert(0, str(ROOT / 'build-support/update'))
    from release_assets import request
    record = reserve(commit, source_tree_sha256(), IDENTITY['version'], run_id, request)
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as outputs:
        outputs.write(f'build={record["build"]}\nrelease_tag={record["tag"]}\n')
    print(f'Reserved {record["tag"]}, build {record["build"]}, for this GitHub workflow run.')


if __name__ == '__main__':
    main()
