"""Replay reviewed public responses from run 40468990139; ZERO provider calls.

Defaults to static normalization only. --execute invokes the existing capped,
offline Docker verifier. Original answers, strict results and paid trial records
are not overwritten. Assisted records cannot enter the original comparator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from .model_diff_normalization import normalize_saved_response, POLICY_VERSION
from .bugsinpy_patch_verifier import verify_patch
from .bugsinpy_patch_compare import compare_patch_trials

RUN_ID = 40468990139
BUGGY = 'a4b9c86db548b2d0dbb5af7a6bbdc26ab47e1eec'
PROMPT = '61ccab1c4720890c83f752caa9bc275da94352660c834a7bd4273521314b6c2c'
EXPECTED = {
    'l2': ('claude-sonnet-5-5', '23c56ee4e55dd3bbbaef99f3aef7a2230577b7ebf7ea3b7999f0bff3d7bf566b', 'regression_passed', True),
    'l3': ('claude-opus-5-5', '299a445bbe84f2247afe1e4d6bf64e0501b4ae10508909fd013e25302f06f463', 'invalid_candidate_diff', None),
}
ASSISTED_EVALUATION = 'normalized_saved_response_regression_only'


def load_archive(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 500_000:
        raise ValueError('Expected bounded regular archive fixture')
    data = json.loads(path.read_text(encoding='utf-8'))
    if (data.get('source_run_id') != RUN_ID or data.get('case_id') != 'tqdm-6'
            or data.get('buggy_commit') != BUGGY or data.get('prompt_sha256') != PROMPT
            or data.get('source_context_version') != 'full-pinned-files-v2'
            or set(data.get('responses', {})) != {'l2', 'l3'}):
        raise ValueError('Only the reviewed frozen full-context trial is accepted')
    for tier, (model, digest, status, passed) in EXPECTED.items():
        row = data['responses'][tier]
        text = row.get('text')
        if (not isinstance(text, str) or hashlib.sha256(text.encode('utf-8')).hexdigest() != digest
                or row.get('response_sha256') != digest or row.get('model_id') != model
                or row.get('original_status') != status
                or row.get('original_verified_patch_success') is not passed):
            raise ValueError('Archive response/provenance does not match reviewed bytes')
    return data


def _save(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def replay_pair(archive_file: Path, output_root: Path, workspace: Path,
                dataset_root: Path, *, execute: bool = False) -> dict:
    archived_bytes = archive_file.read_bytes()
    data = load_archive(archive_file)
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError('Use a new empty output directory; archived reports are never overwritten')
    output_root.mkdir(parents=True, exist_ok=True)
    report = {
        'evaluation': ASSISTED_EVALUATION,
        'source_run_id': RUN_ID, 'case_id': 'tqdm-6', 'buggy_commit': BUGGY,
        'source_prompt_sha256': PROMPT, 'source_context_version': data['source_context_version'],
        'normalization_policy': POLICY_VERSION, 'paid_api_calls': 0,
        'executed': bool(execute), 'original_outcomes_unchanged': True, 'results': {},
        'limitations': 'Format-assisted regression-only replay of one historical selected case. '
                       'Not unassisted model success, full-suite correctness or general router accuracy.',
    }
    summary = output_root / 'normalized_replay_summary.json'
    _save(summary, report)
    for tier in ('l2', 'l3'):
        raw = data['responses'][tier]
        row = {
            'model_id': raw['model_id'], 'response_id': raw['response_id'],
            'original_status': raw['original_status'],
            'original_verified_patch_success': raw['original_verified_patch_success'],
            'normalized_regression_passed': None, 'candidate_test_executed': False,
            'status': 'not_prepared',
        }
        report['results'][tier] = row
        _save(summary, report)
        try:
            original_path = output_root / (tier + '_original_response.txt')
            original_path.write_bytes(raw['text'].encode('utf-8'))
            candidate, normalization = normalize_saved_response(
                raw['text'], 'tqdm-6', allow_count_repair=True)
            row['normalization'] = normalization
            patch_file = output_root / (tier + '_normalized.diff')
            patch_file.write_bytes(candidate)
            row['status'] = 'normalized_not_tested'
            _save(summary, report)
            if execute:
                # Canonical verifier records live only in a temporary directory.
                # Public output is explicitly re-tagged before persistence so
                # compare_patch_trials cannot mix it into original trial scores.
                with tempfile.TemporaryDirectory(prefix='assisted_verifier_') as temporary:
                    temporary_root = Path(temporary)
                    verification = verify_patch(
                        dataset_root=dataset_root, workspace=workspace / tier,
                        output_root=temporary_root, case_id='tqdm-6', tier=tier,
                        model_id=raw['model_id'], patch_file=patch_file, execute=True)
                    if verification.get('patch_sha256') != normalization['normalized_patch_sha256']:
                        raise ValueError('Verifier and normalized patch hash mismatch')
                    assisted = dict(verification)
                    assisted['source_verifier_evaluation'] = verification.get('evaluation')
                    assisted['evaluation'] = ASSISTED_EVALUATION
                    assisted['normalization_policy'] = POLICY_VERSION
                    assisted['source_run_id'] = RUN_ID
                    assisted['original_response_sha256'] = raw['response_sha256']
                    assisted['original_score_unchanged'] = True
                    target = output_root / 'assisted_verifier_records'
                    target.mkdir(exist_ok=True)
                    if (temporary_root / 'logs').is_dir():
                        shutil.copytree(temporary_root / 'logs', target / 'logs', dirs_exist_ok=True)
                    _save(target / f'tqdm-6_{tier}.json', assisted)
                    row['verification_file'] = f'assisted_verifier_records/tqdm-6_{tier}.json'
                    row['status'] = verification['status']
                    row['normalized_regression_passed'] = verification['regression_passed']
                    row['candidate_test_executed'] = verification.get('candidate_test_executed', False)
                    row['baseline_verification_status'] = verification.get('baseline_verification_status')
        except Exception as exc:
            row['status'] = 'replay_inconclusive'
            row['error_type'] = type(exc).__name__
            row['normalized_regression_passed'] = None
        _save(summary, report)
    if archive_file.read_bytes() != archived_bytes:
        raise ValueError('Original archive unexpectedly changed')
    original_comparison = compare_patch_trials(output_root / 'assisted_verifier_records')
    if original_comparison['n_complete_pairs'] != 0:
        raise ValueError('Assisted outcomes leaked into original-score comparator')
    report['original_comparator_complete_pairs_from_assisted_records'] = 0
    report['status'] = 'replay_completed_review_evidence'
    _save(summary, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-file', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--dataset-root', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Run existing offline Docker verifier; no model API')
    args = parser.parse_args()
    report = replay_pair(args.archive_file, args.output_root, args.workspace,
                         args.dataset_root, execute=args.execute)
    print(json.dumps({
        'source_run_id': RUN_ID, 'paid_api_calls': 0, 'executed': report['executed'],
        'original_outcomes_unchanged': True,
        'tiers': {tier: {'status': row['status'],
                        'normalized_regression_passed': row['normalized_regression_passed']}
                  for tier, row in report['results'].items()},
    }, indent=2))
    if any(row['status'] == 'replay_inconclusive' for row in report['results'].values()):
        raise SystemExit(2)

if __name__ == '__main__':
    main()
