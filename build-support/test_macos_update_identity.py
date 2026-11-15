"""Authenticate a disposable package with the production native update verifier."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path(os.environ.get('OINK_UPDATE_IDENTITY_TEST_APP', '/nonexistent-oink-reference'))


@unittest.skipUnless(sys.platform == 'darwin' and REFERENCE.is_dir(), 'requires a genuine signed reference Mac app')
class NativeUpdateIdentity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='oink-update-identity-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.identity = json.loads((ROOT / 'packaging/identity.json').read_text())['macos']

    def verifier(self, *, enabled=True, fingerprint=None):
        source = self.directory / 'probe.m'
        source.write_text('int main(int argc,const char **argv) {return argc==2 ? (int)oink_local_verify_app(argv[1]) : 99;}\n')
        binary = self.directory / 'probe'
        subprocess.run(['xcrun', 'clang', '-fobjc-arc', '-fblocks', '-Werror',
                        '-DOINK_ALLOW_DEVELOPMENT_UPDATES=' + str(int(enabled)),
                        '-DOINK_SIGNING_TEAM="' + self.identity['team_id'] + '"',
                        '-DOINK_DEVELOPMENT_FINGERPRINT="' + (fingerprint or self.identity['signing_fingerprint']) + '"',
                        '-include', str(ROOT / 'crates/oink-agent/native/local-update.m'), str(source),
                        '-framework', 'AppKit', '-framework', 'Security', '-o', str(binary)], check=True,
                       capture_output=True)
        return binary

    def test_exact_development_signer_authenticates_without_notarization(self):
        self.assertEqual(subprocess.run([self.verifier(), REFERENCE], capture_output=True).returncode, 0)

    def test_disabled_development_policy_and_other_certificate_are_rejected(self):
        for args in ({'enabled': False}, {'fingerprint': '0' * 40}):
            with self.subTest(args=args):
                self.assertNotEqual(subprocess.run([self.verifier(**args), REFERENCE], capture_output=True).returncode, 0)

    def test_tampered_and_adhoc_resigned_packages_are_rejected(self):
        copy = self.directory / 'Oink.app'
        subprocess.run(['/usr/bin/ditto', str(REFERENCE), str(copy)], check=True, capture_output=True)
        info = copy / 'Contents/Info.plist'
        info.write_bytes(info.read_bytes() + b'\n<!-- modified -->\n')
        binary = self.verifier()
        self.assertNotEqual(subprocess.run([binary, copy], capture_output=True).returncode, 0)
        subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(copy)], check=True, capture_output=True)
        self.assertNotEqual(subprocess.run([binary, copy], capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
