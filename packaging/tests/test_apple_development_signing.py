"""A fork signing identity must be selected and verified without weakening distribution checks."""
import importlib.util
import sys
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('apple_development_signing', Path(__file__).parents[1] / 'macos/signing.py')
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)
TEAM = 'CORPTEAM01'
FINGERPRINT = '0473FF860D7216C626F5F75F66FFE55D82DC24B2'
CERTIFICATE_PEM = '-----BEGIN CERTIFICATE-----\nMIIDMDCCAhgCCQDSIWqxje6HkzANBgkqhkiG9w0BAQsFADBaMTAwLgYDVQQDDCdB\ncHBsZSBEZXZlbG9wbWVudDogRml4dHVyZSAoUEVSU09OQUwwMSkxEzARBgNVBAsM\nCkNPUlBURUFNMDExETAPBgNVBAoMCFRlc3RPbmx5MB4XDTI2MTExMTEzMzc0MFoX\nDTM2MTEwODEzMzc0MFowWjEwMC4GA1UEAwwnQXBwbGUgRGV2ZWxvcG1lbnQ6IEZp\neHR1cmUgKFBFUlNPTkFMMDEpMRMwEQYDVQQLDApDT1JQVEVBTTAxMREwDwYDVQQK\nDAhUZXN0T25seTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAOKhxcYb\nwwzBp1Ay4ekv4Jy+Xy/+tj0+pph+WQiiln2LtdMz1khnAcYbHeaiEnpYtM6LNU4R\nRW1ULjIJZLy7X6OtWnFrKsPsklg/nfGIU5FUL0YaZLAWf6vCSVNfrizezDU+ecEL\nqeW20BsDpw3QpUy2ktWCv3B9nSpv0ZXp3oO2Aos2XM52HYlA4Zi0CDOqSi3GRZZI\nVQass4LbZGO0xUwGwX5lqBHaK6Y9v8p3dBQHXqLdiiSwpGih149S5u+lNLzPOGpp\nAcm7CLkkSUlv4wN6tzBBu1xtNfJWmMopsfj2STfuIoZTLjyLL36qTBrOPIoCkvGY\nL/dDiBsxekps/JECAwEAATANBgkqhkiG9w0BAQsFAAOCAQEA4IzfVxDC7K28ebu9\n1T74RijkWWDjqCKSJKzcmmV0L04LODL/QBsxH7oBuZM8/es9RtVB6Et2uc3Cquqg\n9k5Lf3u+999cJj4W4Vig5V/M8Iq2hi38B/yyF5Z7EFmAJgImKaweJlzKDQbr91Gh\n3XjfGA0K9MByUKLW5VHSLcXMvAfMTIcNVUofff2FJtcpdkdyAek4q3xAd+yjNYBb\neJ0wtJyrllwiLZPoI/9fHzOUB6HaqFmjjvpUk1asrAFMD94XW8iDWm5AEtTkQzW0\n/C/tsTp93ad3YJKq8GSbey/DI/Y0D7dCw6Ps30G1+z5CRZ3rQKgspCkz/BT9nJPR\niBXuGw==\n-----END CERTIFICATE-----\n'
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

    def test_development_selection_uses_certificate_ou_and_rejects_wrong_identity(self):
        entries = '\n'.join([
            f'1) {FINGERPRINT} "Apple Development: Fixture (PERSONAL01)"',
            f'2) {"B" * 40} "Developer ID Application: Fixture ({TEAM})"',
            f'3) {"C" * 40} "Apple Development: Other ({TEAM})"'])
        original = S.private_run
        def external(*args, **kwargs):
            if args[:2] == ('security', 'find-identity'):
                return subprocess.CompletedProcess([], 0, entries, '')
            if args[:2] == ('security', 'find-certificate'):
                return subprocess.CompletedProcess([], 0, CERTIFICATE_PEM, '')
            return original(*args, **kwargs)
        with patch.object(S, 'private_run', side_effect=external):
            self.assertEqual(S.select_identity(TEAM, FINGERPRINT, kind='apple-development'), FINGERPRINT)
            for team, fingerprint in [(TEAM, 'B' * 40), ('OTHERTEAM0', FINGERPRINT), (TEAM, 'C' * 40)]:
                with self.subTest(team=team, fingerprint=fingerprint), self.assertRaises(RuntimeError):
                    S.select_identity(team, fingerprint, kind='apple-development')

    def test_development_verification_requires_apple_authority_and_exact_team(self):
        good = f'Authority=Apple Development: Fixture (PERSONAL01)\nTeamIdentifier={TEAM}\n'
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
