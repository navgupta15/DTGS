"""
GitHub ingestion: clone a public repo and discover Java files.
"""
from __future__ import annotations

import subprocess
import tempfile
import shutil
from pathlib import Path


# REST annotation names to detect (Spring Boot + Jakarta)
REST_ANNOTATION_NAMES = {
    "GetMapping",
    "PostMapping",
    "PutMapping",
    "DeleteMapping",
    "PatchMapping",
    "RequestMapping",
}


def clone_repo(url: str, dest: Path | None = None) -> Path:
    """
    Shallow-clone a public GitHub repository to a temporary directory.

    Args:
        url: Public GitHub repo URL (https://github.com/owner/repo)
        dest: Optional target directory. If None, a temp dir is created.

    Returns:
        Path to the cloned repository root.

    Raises:
        RuntimeError: If git is not available or the clone fails.
    """
    if dest is None:
        dest = Path(tempfile.mkdtemp(prefix="toolmaker_"))

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--quiet", url, str(dest)],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "git is not installed or not on PATH. "
            "Please install Git: https://git-scm.com/downloads"
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to clone repository '{url}'.\n"
            f"git stderr: {result.stderr.strip()}"
        )

    return dest


def find_java_files(root: Path) -> list[Path]:
    """
    Recursively find all .java source files under a directory.

    Excludes common non-source paths: .git, target, build, .gradle, out.

    Args:
        root: Repository root directory.

    Returns:
        Sorted list of absolute paths to .java files.
    """
    excluded_dirs = {".git", "target", "build", ".gradle", "out", ".idea"}

    java_files: list[Path] = []
    for path in root.rglob("*.java"):
        # Skip if any parent dir is in excluded set
        if not any(part in excluded_dirs for part in path.parts):
            java_files.append(path)

    return sorted(java_files)


def cleanup_repo(path: Path) -> None:
    """Remove a cloned repository from disk."""
    shutil.rmtree(path, ignore_errors=True)
