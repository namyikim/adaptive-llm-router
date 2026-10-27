"""Lossless extraction of ONE complete text diff; never repair model code.

Pure parsing only: no network, subprocess, worktree, or API calls. Content
inside a diff is preserved; only an enclosing fence and surrounding prose
may be removed. Ambiguous candidates and malformed hunks fail closed.
"""
from __future__ import annotations

import re


class ModelDiffError(ValueError):
    """The saved response is ambiguous, incomplete or not a supported diff."""


_HEADER = re.compile(r"diff --git a/([A-Za-z0-9_./-]+) b/([A-Za-z0-9_./-]+)")
_INDEX = re.compile(r"index [0-9a-f]{7,64}\.\.[0-9a-f]{7,64}(?: 100644)?")
_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?")
_FENCE = re.compile(r"(`{3,}|~{3,})([A-Za-z0-9_-]*)[ \t]*")
_NO_NL = r"\ No newline at end of file"
_METADATA = ("diff ", "@@", "--- ", "+++ ", "index ", "new file mode",
             "deleted file mode", "old mode", "new mode", "rename ",
             "copy ", "GIT binary patch", "Binary files ", "similarity index")


def _no_hidden_patch(lines: list[str]) -> None:
    """Only ordinary prose may be outside the selected complete diff."""
    for line in lines:
        if not line.strip():
            continue
        if (line.startswith(_METADATA) or line.startswith(("+", "-", " ", "\t"))
                or line == _NO_NL):
            raise ModelDiffError("Ambiguous patch content outside the complete diff")


def _candidate_lines(answer: str) -> list[str]:
    lines = answer.split("\n")
    fences = [(i, _FENCE.fullmatch(line)) for i, line in enumerate(lines)
              if _FENCE.fullmatch(line)]
    if fences:
        if len(fences) != 2:
            raise ModelDiffError("Expected one closed patch fence, not multiple candidates")
        (start, opening), (end, closing) = fences
        if (opening.group(1) != closing.group(1) or closing.group(2)
                or opening.group(2).lower() not in ("", "diff", "patch")):
            raise ModelDiffError("Mismatched or unsupported patch fence")
        _no_hidden_patch(lines[:start] + lines[end + 1:])
        lines = lines[start + 1:end]
    first = next((i for i, line in enumerate(lines)
                  if line.startswith("diff --git ")), None)
    if first is None:
        raise ModelDiffError("No Git unified diff header in provider response")
    _no_hidden_patch(lines[:first])
    return lines[first:]


def _complete_patch_end(lines: list[str]) -> int:
    """Consume every complete same-path file and hunk, then only prose.

    Hunk counts are checked explicitly. git apply's parser can ignore extra
    text after a completed hunk, so git parsing alone is not sufficient here.
    File policy (which project/source paths are permitted) is enforced by
    the caller in addition to this structural check.
    """
    i = 0
    seen = set()
    while i < len(lines):
        header = _HEADER.fullmatch(lines[i])
        if not header or header.group(1) != header.group(2):
            raise ModelDiffError("Malformed or different-path Git diff header")
        name = header.group(1)
        if any(part in ("", ".", "..") for part in name.split("/")) or name in seen:
            raise ModelDiffError("Unsafe or duplicate diff file path")
        seen.add(name)
        i += 1
        if i < len(lines) and lines[i].startswith("index "):
            if not _INDEX.fullmatch(lines[i]):
                raise ModelDiffError("Unsupported index metadata or file mode")
            i += 1
        if (i + 1 >= len(lines) or lines[i] != "--- a/" + name
                or lines[i + 1] != "+++ b/" + name):
            raise ModelDiffError("Missing or mismatched old/new file headers")
        i += 2
        hunks = 0
        while i < len(lines) and lines[i].startswith("@@"):
            match = _HUNK.fullmatch(lines[i])
            if not match:
                raise ModelDiffError("Malformed unified diff hunk header")
            old_start, old_count, new_start, new_count = match.groups()
            old_left = int(old_count) if old_count is not None else 1
            new_left = int(new_count) if new_count is not None else 1
            if ((old_left == 0 and new_left == 0)
                    or (old_left > 0 and int(old_start) == 0)
                    or (new_left > 0 and int(new_start) == 0)):
                raise ModelDiffError("Invalid or empty hunk range")
            i += 1
            previous_body = False
            while old_left or new_left:
                if i >= len(lines):
                    raise ModelDiffError("Truncated hunk: declared lines are missing")
                line = lines[i]
                if line == _NO_NL:
                    if not previous_body:
                        raise ModelDiffError("Misplaced no-newline annotation")
                    previous_body = False
                    i += 1
                    continue
                if not line or line[0] not in " +-":
                    raise ModelDiffError("Truncated or malformed hunk body")
                prefix = line[0]
                old_left -= int(prefix in " -")
                new_left -= int(prefix in " +")
                if old_left < 0 or new_left < 0:
                    raise ModelDiffError("Hunk body exceeds its declared line counts")
                previous_body = True
                i += 1
            if i < len(lines) and lines[i] == _NO_NL:
                if not previous_body:
                    raise ModelDiffError("Misplaced no-newline annotation")
                i += 1
            hunks += 1
        if not hunks:
            raise ModelDiffError("File section has no complete hunk")
        if i < len(lines) and lines[i].startswith("diff --git "):
            continue
        # No hidden second patch, stray edit, malformed later hunk or
        # unsupported metadata may be silently thrown away as explanation.
        _no_hidden_patch(lines[i:])
        return i
    return i


def extract_complete_diff(answer: str) -> bytes:
    """Return exact patch lines; reject missing content instead of guessing."""
    if (not isinstance(answer, str) or not answer.strip()
            or len(answer.encode("utf-8")) > 200_000):
        raise ModelDiffError("Model returned empty or oversized patch response")
    if "\r" in answer or "\x00" in answer:
        raise ModelDiffError("Patch response requires LF text without NUL bytes")
    lines = _candidate_lines(answer)
    end = _complete_patch_end(lines)
    return ("\n".join(lines[:end]) + "\n").encode("utf-8")
