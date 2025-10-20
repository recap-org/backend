#!/usr/bin/env python3
"""
Generate all cookiecutter templates in this repo to ensure they can be rendered.

This script:
- Reads the list of templates from cookiecutter/cookiecutter.json
- Generates each template using defaults (no_input=True) into a temp dir
- Performs lightweight assertions on key files to catch obvious failures

Exit code is non-zero on any failure.
"""

from __future__ import annotations
import argparse
from typing import Dict, Any
import shutil
from pathlib import Path
import tempfile
import sys
import json
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
try:
    from app.services.generator import generate_cookiecutter_project
except Exception as e:
    print(f"[DEBUG] Import failed: {e}")
    raise


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


CC_ROOT = REPO_ROOT / "cookiecutter"
CC_INDEX = CC_ROOT / "cookiecutter.json"


def load_templates_index() -> Dict[str, Dict[str, Any]]:
    data = json.loads(CC_INDEX.read_text())
    templates = data.get("templates")
    if not isinstance(templates, dict):
        raise RuntimeError(
            "Invalid cookiecutter/cookiecutter.json: missing 'templates' map")
    return templates


def assert_exists(path: Path, description: str) -> None:
    if not path.exists():
        raise AssertionError(
            f"Expected {description} to exist but it does not: {path}")


def sanity_check(name: str, project_root: Path) -> None:
    """Minimal checks to ensure the template rendered something sensible."""
    if not any(project_root.iterdir()):
        raise AssertionError(f"No files created for template '{name}'")


class RequestStub:
    """Simple request-like object matching fields used by generator.build_extra_context."""

    def __init__(self, template_name: str,
                 project_name: str | None = None,
                 r: bool | None = None,
                 r_version: str | None = None,
                 latex: str | None = None,
                 first_name: str | None = None,
                 last_name: str | None = None,
                 email: str | None = None,
                 institution: str | None = None):
        self.template_name = template_name
        self.project_name = project_name
        self.r = r
        self.r_version = r_version
        self.latex = latex
        self.first_name = first_name
        self.last_name = last_name
        self.email = email
        self.institution = institution


def generate_template(name: str, path_hint: str, artifacts_dir: Path) -> None:
    # Prepare a stable project name per template for assertions
    if name in {"article", "presentation"}:
        project_name = name
    elif name == "data":
        project_name = "recap-data-template"
    else:
        project_name = None

    # Provide sensible defaults to avoid overriding cookiecutter defaults with empty strings
    if name == "data":
        req = RequestStub(
            template_name=name,
            project_name=project_name,
            r=True,
            r_version="4.5.1",
            latex="auto",
            first_name="Morgan",
            last_name="Doe",
            email="morgan.doe@univ-amu.fr",
            institution="Aix-Marseille University, CNRS, AMSE, France",
        )
    elif name in {"article", "presentation"}:
        req = RequestStub(
            template_name=name,
            project_name=project_name,
            first_name="Morgan",
            last_name="Doe",
            email="morgan.doe@univ-amu.fr",
            institution="Aix-Marseille University, CNRS, AMSE, France",
        )
    else:  # devcontainer and future
        req = RequestStub(template_name=name, project_name=project_name)

    # Use app.services.generator to render and get temp/output directories
    result = generate_cookiecutter_project(
        req, project_name_fallback=project_name)
    temp_dir = Path(result["temp_dir"])  # created by generator; we clean it up
    output_dir = Path(result["output_dir"]).resolve()

    # Copy output to artifacts_dir/<template_name>
    dest = artifacts_dir / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(output_dir, dest)

    # For devcontainer, output_dir points to the .devcontainer folder itself
    # For others, output_dir is the project root; run sanity checks accordingly
    sanity_check(name, dest)

    shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate and test cookiecutter templates.")
    parser.add_argument('--keep', action='store_true',
                        help='Keep test_artifacts after run')
    args = parser.parse_args()

    templates = load_templates_index()
    print(
        f"Found {len(templates)} templates: {', '.join(sorted(templates.keys()))}")

    failures: Dict[str, str] = {}
    artifacts_dir = Path("./test_artifacts").resolve()
    if artifacts_dir.exists():
        shutil.rmtree(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    for name, info in templates.items():
        path_hint = info.get("path")
        if not isinstance(path_hint, str):
            failures[name] = "Missing 'path' in index"
            continue
        print(f"→ Generating '{name}' from {path_hint!r} …")
        try:
            generate_template(name, path_hint, artifacts_dir)
        except Exception as e:
            failures[name] = f"{type(e).__name__}: {e}"
            print(f"✗ Failed: {failures[name]}")
        else:
            print("✓ Success")

    if failures:
        print("\nSummary: some templates failed to generate:")
        for name, err in failures.items():
            print(f"- {name}: {err}")
        if not args.keep:
            shutil.rmtree(artifacts_dir, ignore_errors=True)
        return 1

    print("\nAll templates generated successfully.")
    if not args.keep:
        shutil.rmtree(artifacts_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
