"""
FastAPI backend for dynamically generating and serving cookiecutter templates.
"""
import os
import json
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from zipfile import ZipFile, ZipInfo
import io

from fastapi import FastAPI, HTTPException, Query, Header, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, Field
from cookiecutter.main import cookiecutter
import httpx

try:
    from .config import settings
except ImportError:
    # Fallback for running directly
    import os
    class Settings:
        app_name = 'Recap Template API'
        app_version = '1.0.0'
        allowed_origins = ['*']
        cookiecutter_base_path = 'cookiecutter'
        github_api_url = 'https://api.github.com'
        github_default_org = None
        github_client_id = os.environ.get('GITHUB_CLIENT_ID')
        github_client_secret = os.environ.get('GITHUB_CLIENT_SECRET')
        github_redirect_uri = os.environ.get('GITHUB_REDIRECT_URI')
        session_secret_key = os.environ.get('SESSION_SECRET_KEY', 'change-this-in-production')
        session_cookie_name = os.environ.get('SESSION_COOKIE_NAME', 'recap_session')
        session_https_only = os.environ.get('SESSION_HTTPS_ONLY', 'False') == 'True'
        session_same_site = os.environ.get('SESSION_SAME_SITE', 'lax')
        session_max_age = int(os.environ.get('SESSION_MAX_AGE', str(14 * 24 * 60 * 60)))
    settings = Settings()


# Initialize FastAPI app
app = FastAPI(
    title=settings.app_name,
    description="API for generating cookiecutter templates dynamically",
    version=settings.app_version
)

# Configure CORS to allow the Jekyll frontend to access the API
app.add_middleware(
    CORSMiddleware,
    # In production, replace with specific domain
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sessions for OAuth
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    session_cookie=settings.session_cookie_name,
    https_only=settings.session_https_only,
    same_site=settings.session_same_site,  # type: ignore
    max_age=settings.session_max_age,
)

# Path to cookiecutter templates
COOKIECUTTER_BASE = Path(__file__).parent.parent / \
    settings.cookiecutter_base_path


class TemplateInfo(BaseModel):
    """Information about a template."""
    path: str
    title: str
    description: str


class TemplateListResponse(BaseModel):
    """Response model for listing available templates."""
    templates: Dict[str, TemplateInfo]


class TemplateRequest(BaseModel):
    """Request model for generating a template."""
    template_name: str = Field(
        "data", description="Name of the template (data, article, presentation, devcontainer)")
    project_name: str = Field(
        "my-project", description="Name of the project; used as directory name")
    r: Optional[bool] = Field(True, description="Use R?")
    r_version: Optional[str] = Field("4.5.1", description="R version")
    latex: Optional[str] = Field(
        "auto", description="LaTeX package list (auto, full, curated)")
    first_name: Optional[str] = Field(
        "Morgan", description="Author's first name")
    last_name: Optional[str] = Field("Doe", description="Author's last name")
    email: Optional[str] = Field(
        "morgan.doe@example.com", description="Author's email")
    institution: Optional[str] = Field(
        "Your Institution", description="Author's institution")



# --- Combined request for repo creation and template generation ---
class GitHubRepoRequest(TemplateRequest):
    """Request body for creating a GitHub repository and populating it with a template."""
    description: Optional[str] = Field(None, description="Repository description")
    private: bool = Field(True, description="Create as private repository")
    org: Optional[str] = Field(None, description="Organization login; if provided or configured, create repo in org")
    auto_init: bool = Field(False, description="Initialize the repository with an empty README (ignored, always false)")
    allow_squash_merge: Optional[bool] = None
    allow_merge_commit: Optional[bool] = None
    allow_rebase_merge: Optional[bool] = None
    delete_branch_on_merge: Optional[bool] = None


class GitHubRepoResponse(BaseModel):
    """Subset of GitHub repo fields returned to client."""
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


from .services.generator import (
    generate_cookiecutter_project,
    zip_directory_with_symlinks,
)


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "message": settings.app_name,
        "version": settings.app_version,
        "status": "operational",
        "endpoints": {
            "/health": "Health check endpoint",
            "/templates": "List available templates",
            "/templates/{template_name}/config": "Get template configuration",
            "/download": "Generate a template and download it",
            "/gh-repo-create": "Generate a template and create a GitHub repository for the authenticated user or org",
            "/auth/github/login": "Start GitHub OAuth login flow",
            "/auth/github/callback": "OAuth callback endpoint",
            "/auth/github/me": "Get the authenticated GitHub user (if logged in)"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    templates_exist = COOKIECUTTER_BASE.exists()
    return JSONResponse(
        status_code=200 if templates_exist else 503,
        content={
            "status": "healthy" if templates_exist else "unhealthy",
            "version": settings.app_version,
            "templates_directory_exists": templates_exist,
            "templates_path": str(COOKIECUTTER_BASE)
        }
    )


@app.get("/templates", response_model=TemplateListResponse)
async def list_templates():
    """List all available cookiecutter templates."""
    cookiecutter_json_path = COOKIECUTTER_BASE / "cookiecutter.json"

    if not cookiecutter_json_path.exists():
        raise HTTPException(
            status_code=500, detail="Template configuration not found")

    with open(cookiecutter_json_path, 'r') as f:
        data = json.load(f)

    return TemplateListResponse(templates=data["templates"])


@app.get("/templates/{template_name}/config")
async def get_template_config(template_name: str):
    """Get the configuration options for a specific template."""
    # Load main cookiecutter.json to find template path
    main_config_path = COOKIECUTTER_BASE / "cookiecutter.json"

    if not main_config_path.exists():
        raise HTTPException(
            status_code=500, detail="Template configuration not found")

    with open(main_config_path, 'r') as f:
        main_config = json.load(f)

    if template_name not in main_config["templates"]:
        raise HTTPException(
            status_code=404, detail=f"Template '{template_name}' not found")

    # Load template-specific cookiecutter.json
    template_path = COOKIECUTTER_BASE / \
        main_config["templates"][template_name]["path"]
    template_config_path = template_path / "cookiecutter.json"

    if not template_config_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Configuration for template '{template_name}' not found")

    with open(template_config_path, 'r') as f:
        template_config = json.load(f)

    return template_config


@app.post("/download")
async def generate_template(request: TemplateRequest):
    """
    Generate a cookiecutter template based on the provided parameters.
    Returns a zip file containing the generated project.
    """
    # Use shared generator
    gen = generate_cookiecutter_project(request)
    temp_dir = gen["temp_dir"]
    output_dir = Path(gen["output_dir"]) 

    try:
        zip_buffer = zip_directory_with_symlinks(output_dir)

        project_name_safe = (request.project_name or "project").lower().replace(' ', '-')
        filename = f"{project_name_safe}.zip"

        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)



import subprocess

@app.post("/gh-repo-create", response_model=GitHubRepoResponse)
async def gh_repo_create(
    body: GitHubRepoRequest,
    request: Request,
    authorization: Optional[str] = Header(None, description="Bearer token for GitHub API: 'Bearer <token>'"),
):
    """
    Create a GitHub repository and populate it with a cookiecutter template.
    """
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    else:
        token = request.session.get("github_token") or os.environ.get("GITHUB_TOKEN")

    if not token:
        raise HTTPException(status_code=401, detail="Missing GitHub token. Provide 'Authorization: Bearer <token>' header or set GITHUB_TOKEN env var.")

    api_base = getattr(settings, 'github_api_url', 'https://api.github.com').rstrip('/')
    org = body.org or getattr(settings, 'github_default_org', None)
    # Ignore placeholder/invalid org names
    if org:
        url = f"{api_base}/orgs/{org}/repos"
    else:
        url = f"{api_base}/user/repos"

    # Derive repo name from project_name (fallback to 'project')
    repo_name = (body.project_name or "project").strip()
    # simple slug: lower, spaces->-, strip invalid minimal
    repo_name_slug = "-".join(repo_name.lower().split())

    # Build payload per GitHub API
    payload = {
        "name": repo_name_slug,
        "description": body.description,
        "private": body.private,
        "auto_init": False,  # always false, we'll push files ourselves
    }
    if body.allow_squash_merge is not None:
        payload["allow_squash_merge"] = body.allow_squash_merge
    if body.allow_merge_commit is not None:
        payload["allow_merge_commit"] = body.allow_merge_commit
    if body.allow_rebase_merge is not None:
        payload["allow_rebase_merge"] = body.allow_rebase_merge
    if body.delete_branch_on_merge is not None:
        payload["delete_branch_on_merge"] = body.delete_branch_on_merge

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"GitHub API request failed: {e}")

    if resp.status_code >= 400:
        detail = None
        try:
            err = resp.json()
            # GitHub returns detailed error info
            if "errors" in err:
                detail = f"{err.get('message', 'Error')}: {err['errors']}"
            else:
                detail = err.get("message") or str(err)
        except Exception:
            detail = resp.text
        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail=f"Unauthorized with provided GitHub token. {detail}")
        if resp.status_code == 403:
            raise HTTPException(status_code=403, detail=detail or "Forbidden creating repository (permissions or policy)")
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"GitHub endpoint not found or organization missing. {detail}")
        if resp.status_code == 422:
            raise HTTPException(status_code=422, detail=f"Repository creation failed: {detail}")
        raise HTTPException(status_code=502, detail=detail or f"GitHub API error {resp.status_code}")

    data = resp.json()
    repo_clone_url = data["clone_url"]
    repo_default_branch = data.get("default_branch", "main")

    # --- Generate cookiecutter template ---
    gen = generate_cookiecutter_project(body, project_name_fallback=repo_name_slug)
    temp_dir = gen["temp_dir"]
    try:
        output_dir = Path(gen["output_dir"])

        # --- Initialize git, commit, and push ---
        repo_dir = Path(output_dir)
        subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", body.email or "noreply@example.com"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", f"{body.first_name or 'User'} {body.last_name or ''}".strip()], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "checkout", "-b", repo_default_branch], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "Initial commit from cookiecutter template"], cwd=repo_dir, check=True, capture_output=True, text=True)
        # Set remote with token
        clone_url_with_token = repo_clone_url.replace("https://", f"https://{token}@")
        subprocess.run(["git", "remote", "add", "origin", clone_url_with_token], cwd=repo_dir, check=True, capture_output=True, text=True)
        # Push with --set-upstream for new repos
        push_result = subprocess.run(["git", "push", "--set-upstream", "origin", repo_default_branch], cwd=repo_dir, capture_output=True, text=True)
        if push_result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Git push failed: {push_result.stderr}")

    except subprocess.CalledProcessError as e:
        stderr_output = getattr(e, 'stderr', '') or ''
        raise HTTPException(status_code=500, detail=f"Git operation failed: {stderr_output or str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating or pushing template: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # Map to response model
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


# --- GitHub OAuth: Login and Callback ---
from .auth import router as auth_router
app.include_router(auth_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
