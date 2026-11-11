"""A reserved public version changes every package label without rewriting source."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'build-support'))
import identity


class ReleaseIdentity(unittest.TestCase):
    def test_public_version_override_preserves_signer_and_source_manifest(self):
        path = ROOT / 'packaging/identity.json'
        before = path.read_bytes()
        original = identity.load_identity({})
        selected = identity.load_identity({'OINK_PUBLIC_RELEASE_VERSION': '1.0.6'})
        self.assertEqual(selected, {**original, 'version': '1.0.6'})
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn('custom', selected['version'])

    def test_invalid_or_older_public_versions_are_rejected(self):
        for version in ('', '0.0.1', '1.0.6-custom.1', '1.0.6\nunsafe', '01.0.6', '1.0'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                identity.load_identity({'OINK_PUBLIC_RELEASE_VERSION': version})

    def test_builders_share_the_explicit_version_and_local_default_stays_unchanged(self):
        original = json.loads((ROOT / 'packaging/identity.json').read_bytes())['version']
        script = '''import json, runpy, sys
from pathlib import Path
root = Path(sys.argv[1]);sys.path[:0] = [str(root/'build-support'),str(root/'packaging/macos')]
from identity import IDENTITY
values = [IDENTITY['version']]
for path in ('build-support/build.py','build-support/package.py','packaging/macos/build.py','packaging/windows/build.py'):
    module=runpy.run_path(str(root/path),run_name='identity_probe')
    values.append(module.get('IDENTITY',module.get('I'))['version'])
print(json.dumps(values))'''
        for selected in (None, '1.0.6'):
            environment = {k: v for k, v in os.environ.items() if k != 'OINK_PUBLIC_RELEASE_VERSION'}
            if selected:
                environment['OINK_PUBLIC_RELEASE_VERSION'] = selected
            result = subprocess.check_output([sys.executable, '-c', script, str(ROOT)],env=environment,text=True)
            self.assertEqual(json.loads(result), [selected or original] * 5)


if __name__ == '__main__':
    unittest.main()
