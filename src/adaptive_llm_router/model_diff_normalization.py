"""Explicit format assistance for SAVED responses, never a default score repair.

No network, model calls, source execution, inferred source lines or offset
relocation. The original strict parser stays unchanged. Recounting cannot prove
that a model intended no additional lines: this is a separate assisted protocol,
requiring ordinary git applicability checks and independent regression tests.
"""
from __future__ import annotations

import hashlib
import json
import re

from .model_diff import ModelDiffError, extract_complete_diff
from .bugsinpy_patch_verify import inspect_patch
from .bugsinpy_reproduce import ReplayError

POLICY_VERSION = 'saved-response-count-only-v1'
_HEADER = re.compile(r'diff --git a/([A-Za-z0-9_./-]+) b/([A-Za-z0-9_./-]+)')
_HUNK = re.compile(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)')
_FENCE = re.compile(r'(`{3,}|~{3,})([A-Za-z0-9_-]*)[ \t]*')
_NO_NL = '\\ No newline at end of file'
_METADATA = ('diff ', '@@', '--- ', '+++ ', 'index ', 'new file mode',
             'deleted file mode', 'old mode', 'new mode', 'rename ', 'copy ',
             'GIT binary patch', 'Binary files ', 'similarity index')

class NormalizationError(ValueError):
    pass


def _one_explicit_patch(answer: str) -> list[str]:
    lines = answer.split('\n')
    fences = [(i, _FENCE.fullmatch(line)) for i, line in enumerate(lines)
              if _FENCE.fullmatch(line)]
    if fences:
        if len(fences) != 2:
            raise NormalizationError('Need exactly one closed patch fence')
        (start, opening), (end, closing) = fences
        if (opening.group(1) != closing.group(1) or closing.group(2)
                or opening.group(2).lower() not in ('', 'diff', 'patch')):
            raise NormalizationError('Mismatched patch fence')
        for line in lines[:start] + lines[end + 1:]:
            stripped = line.lstrip()
            if (stripped.startswith(_METADATA) or stripped == _NO_NL
                    or stripped.startswith(('```', '~~~', '+'))):
                raise NormalizationError('Additional patch material outside the fence')
        # One explicit fence is the boundary. Ordinary outside explanation,
        # including Markdown bullets, is archived but never interpreted as code.
        lines = lines[start + 1:end]
    elif any(line.lstrip().startswith(('```', '~~~')) for line in lines):
        raise NormalizationError('Malformed patch fence')
    while lines and lines[0] == '':
        lines.pop(0)
    while lines and lines[-1] == '':
        lines.pop()
    if not lines or not lines[0].startswith('diff --git '):
        raise NormalizationError('Count repair requires an explicit complete patch block')
    return lines


def _recount(lines: list[str]) -> tuple[list[str], list[dict], list[dict]]:
    result, changes, bodies = [], [], []
    i = 0
    while i < len(lines):
        header = _HEADER.fullmatch(lines[i])
        if not header or header.group(1) != header.group(2):
            raise NormalizationError('Unsupported file header')
        path = header.group(1)
        result.append(lines[i])
        i += 1
        if i < len(lines) and lines[i].startswith('index '):
            result.append(lines[i])
            i += 1
        if lines[i:i + 2] != ['--- a/' + path, '+++ b/' + path]:
            raise NormalizationError('Missing matching old/new file headers')
        result.extend(lines[i:i + 2])
        i += 2
        n_hunks = 0
        while i < len(lines) and lines[i].startswith('@@'):
            original_header = lines[i]
            match = _HUNK.fullmatch(original_header)
            if not match:
                raise NormalizationError('Malformed hunk header')
            old_start, old_count, new_start, new_count, suffix = match.groups()
            i += 1
            body = []
            while i < len(lines) and not lines[i].startswith(('@@', 'diff --git ')):
                line = lines[i]
                if line == _NO_NL:
                    if not body or body[-1] == _NO_NL:
                        raise NormalizationError('Misplaced no-newline marker')
                elif not line or line[0] not in ' +-':
                    raise NormalizationError('Non-diff content inside patch body')
                body.append(line)
                i += 1
            before = sum(line.startswith((' ', '-')) for line in body)
            after = sum(line.startswith((' ', '+')) for line in body)
            if (not body or not before or not after or int(old_start) == 0
                    or int(new_start) == 0 or not any(x.startswith(('+', '-')) for x in body)):
                raise NormalizationError('Need nonempty existing-file edit with original offsets')
            updated_header = original_header
            if before != int(old_count or 1) or after != int(new_count or 1):
                updated_header = f'@@ -{old_start},{before} +{new_start},{after} @@{suffix}'
                changes.append({'path': path, 'before': original_header,
                                'after': updated_header})
            result.append(updated_header)
            result.extend(body)
            bodies.append({'path': path, 'old_start': old_start,
                           'new_start': new_start, 'lines': body})
            n_hunks += 1
        if not n_hunks:
            raise NormalizationError('File contains no complete edit')
    return result, changes, bodies


def _body_hash(bodies: list[dict]) -> str:
    return hashlib.sha256(json.dumps(bodies, ensure_ascii=False,
                         separators=(',', ':')).encode('utf-8')).hexdigest()


def normalize_saved_response(answer: str, case_id: str, *,
                             allow_count_repair: bool = False) -> tuple[bytes, dict]:
    if (not isinstance(answer, str) or not answer.strip()
            or len(answer.encode('utf-8')) > 200_000 or '\x00' in answer or '\r' in answer):
        raise NormalizationError('Require bounded UTF-8 LF text')
    strict_error = None
    try:
        strict_patch = extract_complete_diff(answer)
    except ModelDiffError as exc:
        strict_patch = None
        strict_error = str(exc)
    try:
        if strict_patch is not None:
            inspect_patch(strict_patch, case_id)
            lines = strict_patch.decode('utf-8').splitlines()
            _, _, bodies = _recount(lines)
            output, changes, before_bodies = strict_patch, [], bodies
        else:
            if not allow_count_repair:
                raise NormalizationError('Explicit count-repair opt-in required: ' + strict_error)
            lines = _one_explicit_patch(answer)
            updated, changes, before_bodies = _recount(lines)
            proposed = ('\n'.join(updated) + '\n').encode('utf-8')
            output = extract_complete_diff(proposed.decode('utf-8'))
            if output != proposed:
                raise NormalizationError('Strict parser changed normalized patch bytes')
            inspect_patch(output, case_id)
            _, residual_changes, bodies = _recount(output.decode('utf-8').splitlines())
            if residual_changes:
                raise NormalizationError('Normalization is not idempotent')
    except (ReplayError, ModelDiffError) as exc:
        raise NormalizationError(str(exc)) from exc
    before_hash, after_hash = _body_hash(before_bodies), _body_hash(bodies)
    if before_hash != after_hash:
        raise NormalizationError('Source edits or original offsets were changed')
    return output, {
        'normalization_policy': POLICY_VERSION,
        'strict_original_accepted': strict_patch is not None,
        'strict_original_error': strict_error,
        'count_repair_enabled': bool(allow_count_repair),
        'response_sha256': hashlib.sha256(answer.encode('utf-8')).hexdigest(),
        'normalized_patch_sha256': hashlib.sha256(output).hexdigest(),
        'envelope_removed': answer != output.decode('utf-8'),
        'count_changes': changes,
        'body_preserved': True,
        'body_sha256_before': before_hash, 'body_sha256_after': after_hash,
        'source_lines_or_offsets_rewritten': False,
        'regression_test_passed': None,
        'note': 'Formatting-assisted artifact, not a replacement for the original score.',
    }
