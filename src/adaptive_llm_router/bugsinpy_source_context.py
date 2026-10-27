"""Complete immutable source context; no model calls or source execution."""
from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from pathlib import Path

from .bugsinpy_reproduce import ReplayError

CONTEXT_VERSION = "full-pinned-files-v2"
MAX_SOURCE_BYTES = 200_000
MAX_TOTAL_SOURCE_BYTES = 300_000


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          capture_output=True, timeout=30).stdout


def _definitions(source: str) -> tuple[list[dict], str]:
    # Parsing is not importing/executing the historical module.
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], "unavailable_historical_syntax"
    rows = []

    def visit(node, parents):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                names = parents + [child.name]
                rows.append({"name": ".".join(names), "start_line": child.lineno,
                             "end_line": child.end_lineno})
                visit(child, names)
            else:
                visit(child, parents)

    visit(tree, [])
    return rows, "indexed"


def complete_source_context(root: Path, commit: str, paths: set[str]) -> tuple[str, list[dict]]:
    """Read complete original Git blobs, never dirty working files or fixes.

    Over-limit source is rejected before a provider call, never silently
    truncated. The location index is display metadata, not source code.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ReplayError("Invalid pinned source commit")
    sections, manifest = [], []
    total = 0
    for name in sorted(paths):
        if (not re.fullmatch(r"[A-Za-z0-9_./-]+", name)
                or name.startswith("/") or any(p in ("", ".", "..") for p in name.split("/"))):
            raise ReplayError("Unsafe source path")
        listing = _git(root, "ls-tree", "-z", commit, "--", name).split(b"\0")
        entries = [entry for entry in listing if entry]
        if len(entries) != 1:
            raise ReplayError("Missing or ambiguous pinned source file")
        metadata, actual_path = entries[0].split(b"\t", 1)
        mode, kind, blob_sha = metadata.decode("ascii").split()
        if (mode not in ("100644", "100755") or kind != "blob"
                or actual_path.decode("utf-8") != name):
            raise ReplayError("Pinned source must be a regular production file")
        size = int(_git(root, "cat-file", "-s", blob_sha))
        if size <= 0 or size > MAX_SOURCE_BYTES or total + size > MAX_TOTAL_SOURCE_BYTES:
            raiseError = "Complete source exceeds explicit context byte limit; refusing to truncate"
            raise ReplayError(raiseError)
        raw = _git(root, "cat-file", "blob", blob_sha)
        if len(raw) != size or b"\x00" in raw:
            raise ReplayError("Invalid pinned source blob")
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReplayError("Pinned source is not UTF-8 text") from exc
        definitions, index_status = _definitions(source)
        lines = len(source.splitlines())
        entry = {"path": name, "commit": commit, "blob_sha": blob_sha,
                 "source_sha256": hashlib.sha256(raw).hexdigest(),
                 "byte_count": size, "line_count": lines, "complete": True,
                 "definitions": definitions, "definition_index_status": index_status}
        manifest.append(entry)
        index = "\n".join(f"{r['name']}: lines {r['start_line']}-{r['end_line']}"
                          for r in definitions)
        sections.append(f"File: {name}\nOriginal source lines: 1-{lines} (COMPLETE).\n"
                        f"Definition index (metadata, not code):\n{index}\n"
                        f"BEGIN COMPLETE SOURCE: {name}\n{source}\nEND COMPLETE SOURCE: {name}")
        total += size
    return "\n\n".join(sections), manifest
