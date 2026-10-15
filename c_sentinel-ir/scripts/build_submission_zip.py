"""
build_submission_zip.py - package the source as a clean, shareable zip.

Zips exactly the hand-written source and deployment files - no virtual environment, no __pycache__, no container layers, no
git history, no local .env. Written as an explicit include list rather than
"everything except .gitignore" so a new stray file never sneaks into a
package by accident.

    python scripts/build_submission_zip.py              # Deliverable 1
    python scripts/build_submission_zip.py --phase 2    # Phase 2

Produces docs/evidence/sentinel-ir-deliverable1-code.zip, or
sentinel-ir-phase2-code.zip for Phase 2. Not committed - it is a build
artefact regenerated from the checked-in source, and is the last step before
uploading to Dropbox alongside the PDF and the video.

Author: Colile
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"
OUTPUT_NAMES = {
    1: "sentinel-ir-deliverable1-code.zip",
    2: "sentinel-ir-phase2-code.zip",
}

# Top-level folders/files that make up the hand-written system. Docs, specs
# and evidence are excluded here; the code and the report are shipped as
# separate items.
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
]

# Phase 2 adds the SOC, graph and RAG layers and the tests that cover them.
# docs/ goes in too: the security workflow reads its attack capture from
# docs/evidence, and the report's evidence index points at the files there.
PHASE2_EXTRA_ROOTS = [
    "soc",
    "kg",
    "rag",
    "tests",
    "data",
    "docs",
    "README.md",
    "pyproject.toml",
    "setup.bat",
    "start.bat",
    "stop.bat",
]

EXCLUDE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "node_modules",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".zip", ".png", ".svg", ".drawio"}
EXCLUDE_NAMES = {".env"}
# docs/report/ ships only the reports themselves, by name, so nothing else
# kept in that folder is packaged by accident.
REPORT_DIR = Path("docs") / "report"
REPORT_FILES = {
    "README.md",
    "deliverable1.md",
    "deliverable2.md",
    "detection-rules.md",
    "rag-demonstration.md",
}


def _should_skip(path: Path) -> bool:
    """
    Purpose: decide whether a file belongs in the package.
    Inputs:  path - a file discovered under one of the include roots.
    Output:  True when the file is build output, cache, or a local secret.
    """
    if any(part in EXCLUDE_DIR_NAMES for part in path.parts):
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    if path.name in EXCLUDE_NAMES:
        return True
    relative = path.relative_to(REPO_ROOT)
    if relative.parent == REPORT_DIR and path.name not in REPORT_FILES:
        return True
    return False


def build_zip(phase: int = 1) -> int:
    """
    Purpose: write every included file into the submission zip.
    Inputs:  phase - 1 for Deliverable 1, 2 to add the Phase 2 layers.
    Output:  the number of files written; also prints Description: value lines.
    """
    output_zip = EVIDENCE_DIR / OUTPUT_NAMES[phase]
    include_roots = INCLUDE_ROOTS + (PHASE2_EXTRA_ROOTS if phase == 2 else [])
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    file_count = 0
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for root_name in include_roots:
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
    print(f"Output: {output_zip}")
    return file_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Package the source as a zip.")
    parser.add_argument("--phase", type=int, choices=sorted(OUTPUT_NAMES), default=1)
    build_zip(parser.parse_args().phase)
