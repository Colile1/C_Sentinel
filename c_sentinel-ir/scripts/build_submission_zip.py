"""
build_submission_zip.py - assemble the Deliverable 1 code zip.

Zips exactly the hand-written source and deployment files the submission sheet
asks for - no virtual environment, no __pycache__, no container layers, no
git history, no local .env. Written as an explicit include list rather than
"everything except .gitignore" so a new stray file never sneaks into a
graded submission by accident.

    python scripts/build_submission_zip.py

Produces docs/evidence/sentinel-ir-deliverable1-code.zip. Not committed - it
is a build artefact regenerated from the checked-in source, and is the last
step before uploading to Dropbox alongside the PDF and the video.

Author: Colile
"""

from __future__ import annotations

import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ZIP = REPO_ROOT / "docs" / "evidence" / "sentinel-ir-deliverable1-code.zip"

# Top-level folders/files that make up the hand-written system. Docs, specs
# and evidence are deliberately excluded - the sheet asks for a code zip and
# a document as two separate items.
INCLUDE_ROOTS = [
    "services",
    "libs",
    "gateway",
    "deploy",
    "client",
    "scripts",
    "registry",
    "observability",
    "requirements.txt",
    "requirements.lock.txt",
    "pytest.ini",
    "CLAUDE.md",
]

EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "node_modules",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
EXCLUDE_NAMES = {".env"}


def _should_skip(path: Path) -> bool:
    """
    Purpose: decide whether a file belongs in the submission zip.
    Inputs:  path - a file discovered under one of the include roots.
    Output:  True when the file is build output, cache, or a local secret.
    """
    if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    return False


def build_zip() -> int:
    """
    Purpose: write every included file into the submission zip.
    Inputs:  none - operates on REPO_ROOT and INCLUDE_ROOTS.
    Output:  the number of files written; also prints Description: value lines.
    """
    OUTPUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
    file_count = 0
    with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as archive:
        for root_name in INCLUDE_ROOTS:
            root_path = REPO_ROOT / root_name
            if root_path.is_file():
                candidates = [root_path]
            elif root_path.is_dir():
                candidates = [p for p in root_path.rglob("*") if p.is_file()]
            else:
                print(f"Skipped missing path: {root_path}")
                continue
            for file_path in candidates:
                if _should_skip(file_path):
                    continue
                arcname = Path("sentinel-ir") / file_path.relative_to(REPO_ROOT)
                archive.write(file_path, arcname)
                file_count += 1
    print(f"Files zipped: {file_count}")
    print(f"Output: {OUTPUT_ZIP}")
    return file_count


if __name__ == "__main__":
    build_zip()
