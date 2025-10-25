"""
Cookiecutter endpoints module.

Endpoints:
- GET    /cookiecutter                          -> list available templates from cookiecutter/cookiecutter.json
- GET    /cookiecutter/{template_name}          -> return template's cookiecutter.json
- POST   /cookiecutter/{template_name}/download -> generate project zip; body optional fields from template config (excludes __prompts__ and _jinja2_env_vars)
- POST   /cookiecutter/{template_name}/github   -> create GitHub repo and push generated project; body = download body + GitHub options
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from cookiecutter.main import cookiecutter
import httpx

from .config import settings
from .services.generator import zip_directory_with_symlinks

router = APIRouter()

# Base directory where cookiecutter templates live
COOKIECUTTER_BASE = Path(__file__).resolve(
).parents[1] / settings.cookiecutter_base_path

# Reserved keys to exclude from request schema building
RESERVED_CONFIG_KEYS = {"__prompts__", "_jinja2_env_vars"}


class TemplateInfo(BaseModel):
    path: str
    title: str
    description: str


class TemplateListResponse(BaseModel):
    templates: Dict[str, TemplateInfo]


class GitHubRepoResponse(BaseModel):
    id: int
    name: str
    full_name: str
    private: bool
    html_url: str
    ssh_url: str
    clone_url: str
    default_branch: str
    description: Optional[str] = None
    visibility: Optional[str] = None


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


def _build_extra_context_from_template(template_name: str, overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    template_cfg = _load_template_config(template_name)
    defaults = {k: v for k, v in template_cfg.items()
                if k not in RESERVED_CONFIG_KEYS}
    extra: Dict[str, Any] = dict(defaults)
    if overrides:
        for k, v in overrides.items():
            if k in RESERVED_CONFIG_KEYS:
                continue
            extra[k] = v
    # Ensure project_name fallback exists
    if not extra.get("project_name"):
        extra["project_name"] = "project"
    return extra


@router.get("/cookiecutter", response_model=TemplateListResponse)
async def list_templates():
    data = _load_main_config()
    return TemplateListResponse(templates=data["templates"])


@router.get("/cookiecutter/{template_name}")
async def get_template_config(template_name: str):
    return _load_template_config(template_name)


@router.post("/cookiecutter/{template_name}/download")
async def download_template(template_name: str, body: Optional[Dict[str, Any]] = None):
    """
    Generate a project zip for a template. Body contains optional overrides for
    variables defined in the template's cookiecutter.json (excluding reserved keys).
    """
    template_path = _resolve_template_path(template_name)
    extra_context = _build_extra_context_from_template(
        template_name, body or {})

    temp_dir = tempfile.mkdtemp()
    try:
        output_dir = cookiecutter(
            str(template_path),
            output_dir=temp_dir,
            no_input=True,
            extra_context=extra_context,
        )
        zip_buffer = zip_directory_with_symlinks(Path(output_dir))
        filename = f"{str(extra_context.get('project_name', 'project')).strip().lower().replace(' ', '-')}.zip"
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating template: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/cookiecutter/{template_name}/github", response_model=GitHubRepoResponse)
async def create_github_repo(
    template_name: str,
    request: Request,
    body: Optional[Dict[str, Any]] = None,
    authorization: Optional[str] = Header(
        None, description="Bearer token for GitHub API: 'Bearer <token>'"),
):
    """
    Create a GitHub repository and push a generated project to it.

    Body = template overrides (same as /download) plus optional GitHub fields:
    - description: str | None
    - private: bool (default True)
    - org: str | None (organization login)
    - allow_squash_merge, allow_merge_commit, allow_rebase_merge, delete_branch_on_merge: bool | None
    """
    overrides = dict(body or {})
    # Extract GitHub options and remove from overrides
    description = overrides.pop("description", None)
    private = bool(overrides.pop("private", True))
    org = overrides.pop("org", None)
    allow_squash_merge = overrides.pop("allow_squash_merge", None)
    allow_merge_commit = overrides.pop("allow_merge_commit", None)
    allow_rebase_merge = overrides.pop("allow_rebase_merge", None)
    delete_branch_on_merge = overrides.pop("delete_branch_on_merge", None)

    # Auth token
    token: Optional[str] = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    else:
        token = request.session.get("github_token") if hasattr(
            request, "session") else None
        token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise HTTPException(
            status_code=401, detail="Missing GitHub token. Provide 'Authorization: Bearer <token>' header or set GITHUB_TOKEN env var.")

    api_base = getattr(settings, "github_api_url",
                       "https://api.github.com").rstrip("/")
    org = org or getattr(settings, "github_default_org", None)
    url = f"{api_base}/orgs/{org}/repos" if org else f"{api_base}/user/repos"

    # Build project context to derive repo name
    extra_context = _build_extra_context_from_template(
        template_name, overrides)
    project_name = str(extra_context.get("project_name") or "project").strip()
    repo_name_slug = "-".join(project_name.lower().split())

    payload: Dict[str, Any] = {
        "name": repo_name_slug,
        "description": description,
        "private": private,
        "auto_init": False,
    }
    if allow_squash_merge is not None:
        payload["allow_squash_merge"] = bool(allow_squash_merge)
    if allow_merge_commit is not None:
        payload["allow_merge_commit"] = bool(allow_merge_commit)
    if allow_rebase_merge is not None:
        payload["allow_rebase_merge"] = bool(allow_rebase_merge)
    if delete_branch_on_merge is not None:
        payload["delete_branch_on_merge"] = bool(delete_branch_on_merge)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"GitHub API request failed: {e}")

    if resp.status_code >= 400:
        try:
            err = resp.json()
            detail = err.get("message")
            if "errors" in err:
                detail = f"{detail or 'Error'}: {err['errors']}"
        except Exception:
            detail = resp.text
        code = resp.status_code
        raise HTTPException(status_code=code if code in (
            401, 403, 404, 422) else 502, detail=detail)

    data = resp.json()
    repo_clone_url = data["clone_url"]
    repo_default_branch = data.get("default_branch", "main")

    # Generate project
    template_path = _resolve_template_path(template_name)
    temp_dir = tempfile.mkdtemp()
    try:
        output_dir = cookiecutter(
            str(template_path),
            output_dir=temp_dir,
            no_input=True,
            extra_context=extra_context,
        )
        repo_dir = Path(output_dir)
        subprocess.run(["git", "init"], cwd=repo_dir,
                       check=True, capture_output=True, text=True)
        # Best-effort user config from context
        email = str(overrides.get("email") or "noreply@example.com")
        full_name = f"{overrides.get('first_name') or 'User'} {overrides.get('last_name') or ''}".strip(
        )
        subprocess.run(["git", "config", "user.email", email],
                       cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", full_name],
                       cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "checkout", "-b", repo_default_branch],
                       cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "-A"], cwd=repo_dir,
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "Initial commit from cookiecutter template"],
                       cwd=repo_dir, check=True, capture_output=True, text=True)
        clone_url_with_token = repo_clone_url.replace(
            "https://", f"https://{token}@")
        subprocess.run(["git", "remote", "add", "origin", clone_url_with_token],
                       cwd=repo_dir, check=True, capture_output=True, text=True)
        push_result = subprocess.run(["git", "push", "--set-upstream", "origin",
                                     repo_default_branch], cwd=repo_dir, capture_output=True, text=True)
        if push_result.returncode != 0:
            raise HTTPException(
                status_code=500, detail=f"Git push failed: {push_result.stderr}")
    except subprocess.CalledProcessError as e:
        raise HTTPException(
            status_code=500, detail=f"Git operation failed: {(e.stderr or str(e)).strip()}")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating or pushing template: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return GitHubRepoResponse(
        id=data["id"],
        name=data["name"],
        full_name=data["full_name"],
        private=data["private"],
        html_url=data["html_url"],
        ssh_url=data["ssh_url"],
        clone_url=data["clone_url"],
        default_branch=repo_default_branch,
        description=data.get("description"),
        visibility=data.get("visibility"),
    )
