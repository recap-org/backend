"""
Cookiecutter generation helpers extracted from main app module.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import Dict, Optional, Any
from zipfile import ZipFile, ZipInfo

from fastapi import HTTPException

# Path to cookiecutter templates
COOKIECUTTER_BASE = Path("./cookiecutter")
# Reserved keys to exclude from request schema building
RESERVED_CONFIG_KEYS = {"__prompts__", "_jinja2_env_vars"}


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


def _load_main_config() -> Dict[str, Any]:
    cfg_path = COOKIECUTTER_BASE / "cookiecutter.json"
    if not cfg_path.exists():
        raise HTTPException(
            status_code=500, detail="Template configuration not found")
    with open(cfg_path, "r") as f:
        return json.load(f)


def _resolve_template_path(template_name: str) -> Path:
    main = _load_main_config()
    if template_name not in main.get("templates", {}):
        raise HTTPException(
            status_code=404, detail=f"Template '{template_name}' not found")
    rel = main["templates"][template_name]["path"]
    path = COOKIECUTTER_BASE / rel
    if not path.exists():
        raise HTTPException(
            status_code=404, detail=f"Template directory not found: {path}")
    return path


def _load_template_config(template_name: str) -> Dict[str, Any]:
    path = _resolve_template_path(template_name)
    cfg = path / "cookiecutter.json"
    if not cfg.exists():
        raise HTTPException(
            status_code=404, detail=f"Configuration for template '{template_name}' not found")
    with open(cfg, "r") as f:
        return json.load(f)


def _config_to_context(context: Dict[str, Any]) -> Dict[str, Any]:
    context = {k: v for k, v in context.items(
    ) if k not in RESERVED_CONFIG_KEYS}
    for k, v in list(context.items()):
        if isinstance(v, list) and v:
            context[k] = v[0]
        elif isinstance(v, dict) and v:
            context[k] = next(iter(v.keys()))
    return context


def _build_extra_context_from_template(template_name: str, overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    template_cfg = _load_template_config(template_name)
    defaults = {k: v for k, v in template_cfg.items()
                if k not in RESERVED_CONFIG_KEYS}
    defaults = _config_to_context(defaults)
    extra: Dict[str, Any] = dict(defaults)
    if overrides:
        for k, v in overrides.items():
            if k in RESERVED_CONFIG_KEYS:
                continue
            if k in extra and not isinstance(v, type(extra[k])):
                raise HTTPException(
                    status_code=400,
                    detail=f"Type mismatch for template parameter '{k}': expected {type(extra[k]).__name__}, got {type(v).__name__}"
                )
            if k in extra:
                extra[k] = v
    return extra
