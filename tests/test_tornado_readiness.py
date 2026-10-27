"""Real local Git fixtures, never API calls or historical source execution."""
import copy
import hashlib
import importlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from adaptive_llm_router.bugsinpy_source_context import complete_source_context
from adaptive_llm_router.bugsinpy_reproduce import EXPECTED_COMMITS, EXPECTED_TEST_COMMANDS


class TornadoReadinessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.gitroot = self.root / 'buggy'
        self.results = self.root / 'results'
        self.results.mkdir()
        self.sources = {
            'tornado/ioloop.py': 'class IOLoop:\n    def current(self): pass\n    def close(self): pass\n',
            'tornado/platform/asyncio.py': 'class BaseAsyncIOLoop:\n    def initialize(self): pass\n    def close(self): pass\n',
        }
        for name, text in self.sources.items():
            path = self.gitroot / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        for cmd in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Test', '-c',
                    'user.email=fixture@example.invalid', 'commit', '-qm', 'synthetic fixture']):
            subprocess.run(['git', '-C', str(self.gitroot), *cmd], check=True, capture_output=True)
        self.sha = subprocess.check_output(['git', '-C', str(self.gitroot), 'rev-parse', 'HEAD'], text=True).strip()
        pins = patch.dict(EXPECTED_COMMITS, {'tornado-6': (self.sha, 'f' * 40)})
        pins.start()
        self.addCleanup(pins.stop)
        prompt, manifest = complete_source_context(self.gitroot, self.sha, set(self.sources))
        self.prompt = prompt
        self.manifest = manifest
        self.summary = {
            'case_id': 'tornado-6', 'buggy_commit': self.sha,
            'source_context_version': 'full-pinned-files-v2',
            'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
            'prompt_bytes': len(prompt.encode()), 'paid_api_enabled': False,
            'patch_tests_enabled': False, 'status': 'dry_run_no_api_no_patch_tests',
            'comparison': {'status': 'not_measured'},
            'results': {tier: {'status': 'not_requested', 'verified_patch_success': None}
                        for tier in ('l2', 'l3')},
        }
        self.write_inputs()

    def write_inputs(self):
        (self.results / 'prompt.txt').write_text(self.prompt, encoding='utf-8')
        (self.results / 'source_manifest.json').write_text(json.dumps(self.manifest))
        (self.results / 'e2e_summary.json').write_text(json.dumps(self.summary))

    def auditor(self):
        name = 'adaptive_llm_router.bugsinpy_tornado_readiness'
        self.assertIsNotNone(importlib.util.find_spec(name), 'Tornado no-API readiness audit missing')
        return importlib.import_module(name).audit_readiness

    def history(self):
        record = {
            'case_id': 'tornado-6', 'buggy_commit': self.sha,
            'fixed_commit_for_verifier_only': 'f' * 40,
            'status': 'reproduced_buggy_fail_fixed_pass',
            'verified_historical_reproduction': True,
            'llm_patch_attempted': False, 'llm_verified_success': None,
            'test_commands': copy.deepcopy(EXPECTED_TEST_COMMANDS['tornado-6']),
            'regression_test_backport': {'no_implementation_patch_copied': True},
            'tests': {'buggy': [], 'fixed': []},
        }
        for version in ('buggy', 'fixed'):
            for i, command in enumerate(record['test_commands'], 1):
                method = command[-1].split('.')[-1]
                log = f'{version}_{i}.log'
                content = (f'FAIL: {method} (tornado.test.asyncio_test.LeakTest)\n'
                           'AssertionError: fixture\nRan 1 test in 0.02s\nFAILED (failures=1)\n'
                           if version == 'buggy' else 'Ran 1 test in 0.02s\nOK\n')
                (self.results / log).write_text(content)
                record['tests'][version].append({
                    'command': command, 'exit_code': 1 if version == 'buggy' else 0,
                    'verdict': 'test_failure' if version == 'buggy' else 'pass',
                    'output_file': log,
                })
        return record

    def test_static_audit_is_not_model_or_historical_success(self):
        result = self.auditor()(self.results, self.gitroot)
        self.assertTrue(result['source_context_ready'])
        self.assertIsNone(result['historical_reproduction_verified'])
        self.assertFalse(result['model_quality_measured'])
        self.assertEqual(result['new_provider_calls'], 0)
        self.assertEqual(len(result['files']), 2)
        for tier in ('l2', 'l3'):
            self.assertIsNone(result['model_outcomes'][tier])

    def test_truncation_rejected_even_with_recomputed_prompt_hash(self):
        self.prompt = self.prompt.replace(self.sources['tornado/platform/asyncio.py'], '# omitted')
        self.summary['prompt_sha256'] = hashlib.sha256(self.prompt.encode()).hexdigest()
        self.summary['prompt_bytes'] = len(self.prompt.encode())
        self.write_inputs()
        with self.assertRaises(ValueError):
            self.auditor()(self.results, self.gitroot)

    def test_duplicate_or_incomplete_manifest_rejected(self):
        audit = self.auditor()
        self.manifest.append(copy.deepcopy(self.manifest[0]))
        self.write_inputs()
        with self.assertRaises(ValueError):
            audit(self.results, self.gitroot)
        self.manifest.pop()
        self.manifest[0]['complete'] = False
        self.write_inputs()
        with self.assertRaises(ValueError):
            audit(self.results, self.gitroot)

    def test_paid_or_measured_inputs_cannot_be_called_no_api_readiness(self):
        self.summary['results']['l3']['verified_patch_success'] = True
        self.write_inputs()
        with self.assertRaises(ValueError):
            self.auditor()(self.results, self.gitroot)

    def test_dirty_worktree_does_not_substitute_pinned_source(self):
        (self.gitroot / 'tornado/ioloop.py').write_text('# dirty working file\n')
        self.assertTrue(self.auditor()(self.results, self.gitroot)['source_context_ready'])

    def test_both_historical_tests_and_logs_are_required(self):
        audit = self.auditor()
        record = self.history()
        path = self.results / 'tornado-6.json'
        path.write_text(json.dumps(record))
        result = audit(self.results, self.gitroot, path)
        self.assertTrue(result['historical_reproduction_verified'])
        self.assertEqual(len(result['historical_tests']), 2)
        record['tests']['buggy'][1]['verdict'] = 'test_not_collected'
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            audit(self.results, self.gitroot, path)
        record['tests']['buggy'][1]['verdict'] = 'test_failure'
        path.write_text(json.dumps(record))
        (self.results / 'buggy_2.log').write_text('ERROR: missing (unittest.loader._FailedTest)\n')
        with self.assertRaises(ValueError):
            audit(self.results, self.gitroot, path)


if __name__ == '__main__':
    unittest.main()
