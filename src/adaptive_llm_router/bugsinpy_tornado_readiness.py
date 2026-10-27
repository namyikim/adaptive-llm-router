"""Read-only readiness audit for the next Tornado-6 pilot; no model calls.

Static source readiness, historical defect reproduction and LLM patch success
are three different measurements. This auditor never infers the last one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from .bugsinpy_reproduce import EXPECTED_COMMITS, EXPECTED_TEST_COMMANDS, REPRODUCED
from .bugsinpy_source_context import complete_source_context, CONTEXT_VERSION

CASE = 'tornado-6'
PATHS = {'tornado/ioloop.py', 'tornado/platform/asyncio.py'}
REQUIRED_DEFINITIONS = {
    'tornado/ioloop.py': {'IOLoop.current', 'IOLoop.close'},
    'tornado/platform/asyncio.py': {'BaseAsyncIOLoop.initialize', 'BaseAsyncIOLoop.close'},
}


def _read(path: Path, limit: int = 2_000_000) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Expected bounded regular evidence file: ' + path.name)
    return path.read_bytes()


def _json(path: Path):
    return json.loads(_read(path).decode('utf-8'))


def _historical_tests(path: Path) -> list[dict]:
    record = _json(path)
    buggy, fixed = EXPECTED_COMMITS[CASE]
    commands = EXPECTED_TEST_COMMANDS[CASE]
    if (record.get('case_id') != CASE or record.get('buggy_commit') != buggy
            or record.get('fixed_commit_for_verifier_only') != fixed
            or record.get('status') != REPRODUCED
            or record.get('verified_historical_reproduction') is not True
            or record.get('llm_patch_attempted') is not False
            or record.get('llm_verified_success') is not None
            or record.get('test_commands') != commands
            or record.get('regression_test_backport', {}).get('no_implementation_patch_copied') is not True):
        raise ValueError('Historical record is not the pinned non-model reproduction')
    groups = record.get('tests', {})
    if any(not isinstance(groups.get(g), list) or len(groups[g]) != 2 for g in ('buggy', 'fixed')):
        raise ValueError('Require both leak tests in each historical version')
    rows = []
    for i, command in enumerate(commands):
        row = {'test': command[-1]}
        method = command[-1].split('.')[-1]
        for version, expected_verdict, expected_exit in (('buggy', 'test_failure', 1), ('fixed', 'pass', 0)):
            item = groups[version][i]
            if (item.get('command') != command or item.get('verdict') != expected_verdict
                    or type(item.get('exit_code')) is not int or item['exit_code'] != expected_exit):
                raise ValueError('Missing, reordered or uncollected historical test')
            log_name = item.get('output_file', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]+\.log', log_name):
                raise ValueError('Unexpected historical log path')
            raw = _read(path.parent / log_name)
            text = raw.decode('utf-8', errors='replace')
            if 'unittest.loader._FailedTest' in text or not re.search(r'^Ran 1 test in ', text, re.M):
                raise ValueError('Log does not prove one collected test')
            if version == 'buggy':
                if (not re.search(r'^FAIL: ' + re.escape(method) + r'\b', text, re.M)
                        or not re.search(r'^AssertionError:', text, re.M)
                        or 'FAILED (failures=1)' not in text):
                    raise ValueError('Missing real leak assertion failure')
            elif not re.search(r'^OK\s*$', text, re.M):
                raise ValueError('Missing fixed-test pass log')
            row[version] = {'verdict': expected_verdict, 'exit_code': expected_exit,
                            'log_file': log_name, 'log_sha256': hashlib.sha256(raw).hexdigest()}
        rows.append(row)
    return rows


def audit_readiness(results_root: Path, buggy_root: Path,
                    reproduction_file: Path | None = None) -> dict:
    summary = _json(results_root / 'e2e_summary.json')
    manifest = _json(results_root / 'source_manifest.json')
    prompt_bytes = _read(results_root / 'prompt.txt')
    prompt = prompt_bytes.decode('utf-8')
    buggy = EXPECTED_COMMITS[CASE][0]
    if (summary.get('case_id') != CASE or summary.get('buggy_commit') != buggy
            or summary.get('source_context_version') != CONTEXT_VERSION
            or summary.get('status') != 'dry_run_no_api_no_patch_tests'
            or summary.get('paid_api_enabled') is not False
            or summary.get('patch_tests_enabled') is not False
            or summary.get('comparison', {}).get('status') != 'not_measured'
            or summary.get('prompt_sha256') != hashlib.sha256(prompt_bytes).hexdigest()
            or summary.get('prompt_bytes') != len(prompt_bytes)):
        raise ValueError('Expected an intact, unpaid Tornado-6 dry-run artifact')
    results = summary.get('results', {})
    if set(results) != {'l2', 'l3'} or any(
            results[tier].get('status') != 'not_requested'
            or results[tier].get('verified_patch_success') is not None for tier in results):
        raise ValueError('Readiness must not contain fabricated/measured model outcomes')
    expected_source, expected_manifest = complete_source_context(buggy_root, buggy, PATHS)
    if manifest != expected_manifest or expected_source not in prompt:
        raise ValueError('Source is truncated, altered, duplicated or from the wrong commit')
    files = []
    for entry in expected_manifest:
        definitions = {row['name']: row for row in entry['definitions']}
        if not REQUIRED_DEFINITIONS[entry['path']].issubset(definitions):
            raise ValueError('Required original lifecycle methods are not indexed')
        files.append({key: entry[key] for key in ('path', 'blob_sha', 'source_sha256', 'byte_count', 'line_count', 'complete')})
        files[-1]['required_definitions'] = [definitions[name] for name in sorted(REQUIRED_DEFINITIONS[entry['path']])]
    historical = _historical_tests(reproduction_file) if reproduction_file is not None else []
    return {
        'evaluation': 'tornado6_preparation_only_not_model_quality',
        'case_id': CASE, 'buggy_commit': buggy, 'source_context_version': CONTEXT_VERSION,
        'source_context_ready': True, 'files': files,
        'prompt_sha256': summary['prompt_sha256'], 'prompt_bytes': len(prompt_bytes),
        'input_tokens_measured': None,
        'historical_reproduction_verified': True if historical else None,
        'historical_tests': historical, 'new_provider_calls': 0,
        'model_quality_measured': False, 'model_outcomes': {'l2': None, 'l3': None},
        'next_step': 'User-authorized model generation remains unexecuted',
        'limitations': 'Public historical selected bug with known file locations and test-derived symptoms. Readiness is not proof of model access, affordability, patch correctness or router accuracy.',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results-root', required=True, type=Path)
    parser.add_argument('--buggy-root', required=True, type=Path)
    parser.add_argument('--reproduction-file', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = audit_readiness(args.results_root, args.buggy_root, args.reproduction_file)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
