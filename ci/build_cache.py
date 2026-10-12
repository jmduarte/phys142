#!/usr/bin/env python3
"""Fingerprint the tracked inputs for independent book and PDF build caches.

Names and contents both participate, so removals and renames invalidate a cache.
Gitlinks are deliberately not opened: the private assignments submodule is not
an input to this public build. Untracked local outputs never enter a key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
from typing import Iterable


CACHE_FORMAT = "phys142-build-inputs-v1"
ASSIGNMENTS = ("assignment1", "assignment2", "assignment3", "final_projects")
HASH_HELPER = "ci/build_cache.py"
ASSEMBLY_HELPER = "ci/assemble_site.py"
DEPLOY_WORKFLOW = ".github/workflows/deploy.yml"
LATEX_ACTION = ".github/actions/cached-latex/action.yml"
SITE_BUILD_LOGIC = {HASH_HELPER, ASSEMBLY_HELPER, DEPLOY_WORKFLOW}
PDF_BUILD_LOGIC = {HASH_HELPER, LATEX_ACTION}
PROSE_SUFFIXES = {".md", ".rst"}
EXECUTION_METADATA = {"kernelspec", "language_info", "execution", "mystnb", "tags"}


def tracked_inputs(root: Path) -> dict[str, bytes]:
    """Read the current contents of tracked files, without descending gitlinks."""
    result = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    inputs = {}
    for entry in result.stdout.split(b"\0"):
        if not entry:
            continue
        header, raw_name = entry.split(b"\t", 1)
        mode, _object_id, stage = header.split()
        name = os.fsdecode(raw_name)
        if stage != b"0":
            raise ValueError(f"Unmerged Git index entry: {name}")
        if mode == b"160000":
            continue
        path = root / name
        # A tracked symlink is an input by its target, not by arbitrary files
        # outside the checkout that the target might happen to resolve to.
        if mode == b"120000":
            inputs[name] = os.fsencode(os.readlink(path))
        else:
            inputs[name] = path.read_bytes()
    return inputs


def fingerprint(inputs: Iterable[tuple[str, bytes]]) -> str:
    """Hash a length-delimited, sorted manifest independent of file mtimes."""
    digest = hashlib.sha256(CACHE_FORMAT.encode())
    for name, content in sorted(inputs):
        encoded_name = name.encode("utf-8", errors="surrogateescape")
        for part in (encoded_name, content):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def site_input(name: str) -> bool:
    if name in SITE_BUILD_LOGIC or name == "syllabus/syllabus.bib":
        return True
    top = PurePosixPath(name).parts[0]
    # TeX documents have their own build inputs. Other tracked source, code,
    # data and assets are included conservatively, including future folders.
    return (
        top not in {"assignments", "syllabus", ".github", "ci", "tests"}
        and name not in {".gitignore", ".gitmodules"}
    )


def execution_input(name: str) -> bool:
    return (
        site_input(name)
        and name not in {"_toc.yml", ASSEMBLY_HELPER, "syllabus/syllabus.bib"}
        and PurePosixPath(name).suffix not in PROSE_SUFFIXES | {".ipynb"}
    )


def notebook_code(content: bytes) -> bytes:
    """Exclude prose, outputs and counters, retaining executable cell metadata."""
    notebook = json.loads(content)
    metadata = notebook.get("metadata", {})
    executable = {
        "metadata": {key: metadata[key] for key in EXECUTION_METADATA if key in metadata},
        "cells": [
            {
                "source": "".join(cell["source"]),
                "metadata": cell.get("metadata", {}),
            }
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        ],
    }
    return json.dumps(executable, sort_keys=True, separators=(",", ":")).encode()


def build_keys(root: Path, texlive_image: str) -> dict[str, str]:
    inputs = tracked_inputs(root)
    site = {name: content for name, content in inputs.items() if site_input(name)}
    execution = {
        name: content for name, content in inputs.items() if execution_input(name)
    }
    notebooks = {
        name: notebook_code(content)
        for name, content in site.items()
        if PurePosixPath(name).suffix == ".ipynb"
    }
    # Prefix restores let Jupyter Cache reuse unchanged cells after code edits.
    # It does not hash all notebook-level execution settings, so those settings
    # must also partition the restore prefix to prevent stale output reuse.
    for name, content in notebooks.items():
        execution[name] = json.dumps(
            json.loads(content)["metadata"], sort_keys=True, separators=(",", ":")
        ).encode()
    keys = {
        "site": fingerprint(site.items()),
        "execution_context": fingerprint(execution.items()),
        "notebooks": fingerprint(notebooks.items()),
    }
    for document in ("syllabus", *ASSIGNMENTS):
        prefixes = (
            ("syllabus/",) if document == "syllabus"
            else (f"assignments/{document}/", "assignments/common/")
        )
        sources = {
            name: content
            for name, content in inputs.items()
            if name in PDF_BUILD_LOGIC or name.startswith(prefixes)
        }
        sources["@texlive-image"] = texlive_image.encode()
        keys[document] = fingerprint(sources.items())
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--texlive-image", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    keys = build_keys(args.root, args.texlive_image)
    output = "".join(f"{name}={value}\n" for name, value in keys.items())
    print(output, end="")
    output_path = args.github_output or os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(output)


if __name__ == "__main__":
    main()
