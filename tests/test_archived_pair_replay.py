"""Replay protocol tests: archived responses, no provider requests or Docker."""
import hashlib
import importlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from adaptive_llm_router.bugsinpy_patch_compare import compare_patch_trials
from adaptive_llm_router.model_diff import extract_complete_diff, ModelDiffError
FIXTURE = ROOT / 'tests/fixtures/run_40468990139_responses.json'

class ArchivedPairReplayTests(unittest.TestCase):
    def module(self):
        name = 'adaptive_llm_router.bugsinpy_saved_pair_replay'
        self.assertIsNotNone(importlib.util.find_spec(name), 'Audited replay runner missing')
        return importlib.import_module(name)

    def test_frozen_response_hashes_and_dry_run_no_external_tests(self):
        module = self.module()
        original = FIXTURE.read_bytes()
        with tempfile.TemporaryDirectory() as temp, patch.object(
                module, 'verify_patch', side_effect=AssertionError('No execution in dry run')):
            out = Path(temp) / 'out'
            report = module.replay_pair(FIXTURE, out, Path(temp) / 'work', Path(temp) / 'data')
            self.assertEqual(report['paid_api_calls'], 0)
            self.assertFalse(report['executed'])
            self.assertTrue(report['original_outcomes_unchanged'])
            self.assertTrue(report['results']['l2']['original_verified_patch_success'])
            self.assertIsNone(report['results']['l3']['original_verified_patch_success'])
            for tier in ('l2', 'l3'):
                row = report['results'][tier]
                self.assertIsNone(row['normalized_regression_passed'])
                self.assertTrue(row['normalization']['body_preserved'])
                self.assertTrue((out / (tier + '_normalized.diff')).is_file())
            l3 = report['results']['l3']['normalization']
            self.assertFalse(l3['strict_original_accepted'])
            self.assertEqual(l3['count_changes'][0]['after'], '@@ -735,11 +735,12 @@')
            with self.assertRaises(ValueError):
                module.replay_pair(FIXTURE, out, Path(temp) / 'work', Path(temp) / 'data')
        self.assertEqual(FIXTURE.read_bytes(), original)

    def test_modified_archive_is_rejected_before_any_execution(self):
        module = self.module()
        data = json.loads(FIXTURE.read_text())
        data['responses']['l3']['text'] += '\nchanged'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wrong = root / 'wrong.json'
            wrong.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                module.load_archive(wrong)

    def test_assisted_verifier_records_cannot_be_mixed_into_original_comparator(self):
        module = self.module()
        calls = []
        def fake_verifier(**kwargs):
            calls.append(kwargs['tier'])
            self.assertTrue(kwargs['execute'])
            return {'case_id': 'tqdm-6', 'tier': kwargs['tier'], 'model_id': kwargs['model_id'],
                    'evaluation': 'independent_candidate_patch_regression_only',
                    'status': 'regression_passed', 'executed': True,
                    'baseline_verification_status': 'reproduced_buggy_fail_fixed_pass',
                    'regression_passed': True, 'candidate_test_executed': True,
                    'patch_sha256': hashlib.sha256(kwargs['patch_file'].read_bytes()).hexdigest()}
        with tempfile.TemporaryDirectory() as temp, patch.object(
                module, 'verify_patch', side_effect=fake_verifier):
            root = Path(temp)
            report = module.replay_pair(FIXTURE, root / 'out', root / 'work', root / 'data', execute=True)
            self.assertEqual(calls, ['l2', 'l3'])
            self.assertTrue(report['results']['l3']['normalized_regression_passed'])
            self.assertIsNone(report['results']['l3']['original_verified_patch_success'])
            comparison = compare_patch_trials(root / 'out/assisted_verifier_records')
            self.assertEqual(comparison['n_complete_pairs'], 0)
            self.assertIsNone(comparison['overall_six_case_success_rates'])

if __name__ == '__main__':
    unittest.main()
