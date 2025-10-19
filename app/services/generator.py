"""
Cookiecutter generation helpers extracted from main app module.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Optional
from zipfile import ZipFile, ZipInfo

from fastapi import HTTPException
from cookiecutter.main import cookiecutter

from ..config import settings

# Path to cookiecutter templates
COOKIECUTTER_BASE = Path(__file__).resolve().parents[2] / settings.cookiecutter_base_path


def _load_main_cookiecutter_config() -> Dict:
    """Load the main cookiecutter.json configuration and return as dict."""
    main_config_path = COOKIECUTTER_BASE / "cookiecutter.json"
    if not main_config_path.exists():
        raise HTTPException(status_code=500, detail="Template configuration not found")
    with open(main_config_path, 'r') as f:
        return json.load(f)


def resolve_template_path(template_name: str) -> Path:
    """Resolve a template name to its filesystem path, validating existence."""
    main_config = _load_main_cookiecutter_config()
    if template_name not in main_config["templates"]:
        raise HTTPException(status_code=404, detail=f"Template '{template_name}' not found")
    template_rel_path = main_config["templates"][template_name]["path"]
    template_path = COOKIECUTTER_BASE / template_rel_path
    if not template_path.exists():
        raise HTTPException(status_code=404, detail=f"Template directory not found: {template_path}")
    return template_path


def _str_or_empty(val):
    return str(val) if val is not None else ""


def build_extra_context(req, project_name_fallback: Optional[str] = None) -> Dict:
    """Build cookiecutter extra_context based on the template and request values."""
    extra_context: Dict[str, str] = {
        "project_name": _str_or_empty(getattr(req, 'project_name', None) or project_name_fallback),
    }
    if getattr(req, 'template_name', None) == "data":
        extra_context.update({
            "r": _str_or_empty(getattr(req, 'r', None)),
            "r_version": _str_or_empty(getattr(req, 'r_version', None)),
            "latex": _str_or_empty(getattr(req, 'latex', None)),
            "first_name": _str_or_empty(getattr(req, 'first_name', None)),
            "last_name": _str_or_empty(getattr(req, 'last_name', None)),
            "email": _str_or_empty(getattr(req, 'email', None)),
            "institution": _str_or_empty(getattr(req, 'institution', None)),
        })
    elif getattr(req, 'template_name', None) in ["article", "presentation"]:
        extra_context.update({
            "first_name": _str_or_empty(getattr(req, 'first_name', None)),
            "last_name": _str_or_empty(getattr(req, 'last_name', None)),
            "email": _str_or_empty(getattr(req, 'email', None)),
            "institution": _str_or_empty(getattr(req, 'institution', None)),
        })
    return extra_context


def generate_cookiecutter_project(req, project_name_fallback: Optional[str] = None) -> Dict:
    """
    Generate a cookiecutter project for the given request-like object.

    Returns a dict with keys:
      - temp_dir: str (path to temp directory; caller must clean up)
      - output_dir: str (path to generated project directory)
      - template_path: str (template path used)
    """
    template_name = getattr(req, 'template_name', None)
    if not template_name:
        raise HTTPException(status_code=400, detail="Missing template_name")
    template_path = resolve_template_path(template_name)
    extra_context = build_extra_context(req, project_name_fallback=project_name_fallback)

    temp_dir = tempfile.mkdtemp()
    try:
        output_dir = cookiecutter(
            str(template_path),
            output_dir=temp_dir,
            no_input=True,
            extra_context=extra_context,
        )
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Error generating template: {str(e)}")

    return {
        "temp_dir": temp_dir,
        "output_dir": output_dir,
        "template_path": str(template_path),
    }


def zip_directory_with_symlinks(root: Path) -> io.BytesIO:
    """Create an in-memory zip of a directory, preserving symlinks."""
    zip_buffer = io.BytesIO()
    with ZipFile(zip_buffer, 'w') as zip_file:
        for file_path in Path(root).rglob('*'):
            arcname = str(file_path.relative_to(root))
            if file_path.is_symlink():
                zi = ZipInfo(arcname)
                zi.create_system = 3  # Unix
                zi.external_attr = (0o120000 | 0o755) << 16
                link_target = os.readlink(file_path)
                zip_file.writestr(zi, link_target)
            elif file_path.is_file():
                zip_file.write(file_path, arcname)
    zip_buffer.seek(0)
    return zip_buffer
