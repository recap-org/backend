from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from cookiecutter.main import cookiecutter

CC_ROOT = Path("./cookiecutter")
CC_INDEX = CC_ROOT / "cookiecutter.json"


def _load_templates():
    data = json.loads(CC_INDEX.read_text())
    templates = data.get("templates")
    if not isinstance(templates, dict):
        raise RuntimeError(
            "Invalid cookiecutter/cookiecutter.json: missing 'templates' map")
    return templates


def _resolve_template_path(name: str, info: dict) -> Path:
    rel = info.get("path")
    if not isinstance(rel, str):
        raise RuntimeError(f"Template '{name}' missing 'path' in index")
    path = CC_ROOT / rel
    if not path.exists():
        raise RuntimeError(f"Template '{name}' directory not found: {path}")
    return path


def _assert_minimum_files(name: str, out: Path) -> None:
    # Ensure something was generated
    assert out.exists() and out.is_dir(
    ), f"Output dir does not exist for {name}: {out}"
    any_files = any(out.rglob('*'))
    assert any_files, f"No files created for template '{name}'"

    # Template-specific sanity checks
    if name == "article":
        assert (out / "main.tex").exists(), "Expected main.tex in article template"
    elif name == "presentation":
        assert (out / "main.tex").exists(), "Expected main.tex in presentation template"
    elif name == "data":
        assert (out / "Makefile").exists(), "Expected Makefile in data template"
    elif name == "devcontainer":
        # devcontainer renders the folder itself (e.g., .devcontainer)
        assert (
            out / "devcontainer.json").exists(), "Expected devcontainer.json in devcontainer template"


templates_items = list(_load_templates().items())


@pytest.mark.parametrize("name,info", templates_items)
def test_generate_template_defaults(name, info):
    path = _resolve_template_path(name, info)
    tmp = tempfile.mkdtemp()
    try:
        output_dir = cookiecutter(str(path), output_dir=tmp, no_input=True)
        out_path = Path(output_dir)
        _assert_minimum_files(name, out_path)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
