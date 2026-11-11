"""A fork signing identity must be selected and verified without weakening distribution checks."""
import copy
import importlib.util
import sys
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('apple_development_signing', Path(__file__).parents[1] / 'macos/signing.py')
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
TEAM = '9559Z74J33'
FINGERPRINT = 'A' * 40
MAC = {'team_id': TEAM, 'signing_mode': 'apple-development', 'signing_fingerprint': FINGERPRINT}


class AppleDevelopmentSigning(unittest.TestCase):
    def test_local_defaults_select_pinned_development_certificate(self):
        policy = S.signing_configuration(MAC)
        self.assertEqual(policy, {'mode': 'apple-development', 'team': TEAM, 'fingerprint': FINGERPRINT})

    def test_adhoc_and_formal_modes_do_not_inherit_development_fingerprint(self):
        self.assertEqual(S.signing_configuration(MAC, mode='developer-id')['fingerprint'], None)
        self.assertEqual(S.signing_configuration(MAC, development_signing=True)['mode'], 'ad-hoc')
        for options in ({'mode': 'apple-development', 'notary_profile': 'secret'},
                        {'mode': 'ad-hoc', 'fingerprint': FINGERPRINT},
                        {'mode': 'developer-id', 'development_signing': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                S.signing_configuration(MAC, **options)

    def test_development_selection_rejects_wrong_type_team_and_fingerprint(self):
        entries = '\n'.join([
            f'1) {FINGERPRINT} "Apple Development: Fixture ({TEAM})"',
            f'2) {"B" * 40} "Developer ID Application: Fixture ({TEAM})"',
            f'3) {"C" * 40} "Apple Development: Fixture (OTHERTEAM0)"'])
        with patch.object(S, 'private_run', return_value=subprocess.CompletedProcess([], 0, entries, '')):
            self.assertEqual(S.select_identity(TEAM, FINGERPRINT, kind='apple-development'), FINGERPRINT)
            for fingerprint in ('B' * 40, 'C' * 40):
                with self.assertRaises(RuntimeError):
                    S.select_identity(TEAM, fingerprint, kind='apple-development')

    def test_development_verification_requires_apple_authority_and_exact_team(self):
        good = f'Authority=Apple Development: Fixture ({TEAM})\nTeamIdentifier={TEAM}\n'
        with patch.object(S, 'private_run', return_value=subprocess.CompletedProcess([], 0, '', good)):
            S.verify_signature(Path('Oink.app'), TEAM, apple_development=True)
        for details in ('Signature=adhoc\nTeamIdentifier=not set\n', good.replace(TEAM, 'OTHERTEAM0'),
                        good.replace('Apple Development:', 'Developer ID Application:')):
            with patch.object(S, 'private_run', return_value=subprocess.CompletedProcess([], 0, '', details)):
                with self.assertRaises(RuntimeError):
                    S.verify_signature(Path('Oink.app'), TEAM, apple_development=True)

    def test_development_certificate_never_passes_formal_verification(self):
        details = f'Authority=Apple Development: Fixture ({TEAM})\nTeamIdentifier={TEAM}\n'
        with patch.object(S, 'private_run', return_value=subprocess.CompletedProcess([], 0, '', details)):
            with self.assertRaises(RuntimeError):
                S.verify_signature(Path('Oink.app'), TEAM)


class DevelopmentReceipts(unittest.TestCase):
    def test_only_configured_team_and_certificate_can_be_published(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'build-support'))
        from identity import IDENTITY, valid_development_identity
        mac = IDENTITY['macos']
        receipt = {'signing': 'apple-development', 'development_signing': True,
                   'team_id': mac['team_id'], 'certificate_sha1': mac['signing_fingerprint']}
        self.assertTrue(valid_development_identity(receipt))
        for key, value in [('team_id', 'OTHERTEAM0'), ('certificate_sha1', 'F' * 40),
                           ('signing', 'ad-hoc'), ('development_signing', False)]:
            invalid = {**receipt, key: value}
            with self.subTest(field=key):
                self.assertFalse(valid_development_identity(invalid))


if __name__ == '__main__':
    unittest.main()
