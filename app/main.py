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
    https_only=getattr(settings, 'session_https_only', False),
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
        ..., description="Name of the template (data, article, presentation, devcontainer)")
    project_name: Optional[str] = Field(
        "My Project", description="Name of the project")
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
    name: str = Field(..., description="Repository name")
    description: Optional[str] = Field(None, description="Repository description")
    private: bool = Field(True, description="Create as private repository")
    org: Optional[str] = Field(None, description="Organization login; if provided or configured, create repo in org")
    auto_init: bool = Field(False, description="Initialize the repository with an empty README (ignored, always false)")
    gitignore_template: Optional[str] = Field(None, description="Apply a .gitignore template, e.g., 'Python' or 'R' (GitHub templates)")
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
            "/generate": "Generate and download a template",
            "/gh-repo-create": "Create a GitHub repository for the authenticated user or org",
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


@app.post("/generate")
async def generate_template(request: TemplateRequest):
    """
    Generate a cookiecutter template based on the provided parameters.
    Returns a zip file containing the generated project.
    """
    # Load main cookiecutter.json to validate template exists
    main_config_path = COOKIECUTTER_BASE / "cookiecutter.json"

    if not main_config_path.exists():
        raise HTTPException(
            status_code=500, detail="Template configuration not found")

    with open(main_config_path, 'r') as f:
        main_config = json.load(f)

    if request.template_name not in main_config["templates"]:
        raise HTTPException(
            status_code=404, detail=f"Template '{request.template_name}' not found")

    # Get template path
    template_rel_path = main_config["templates"][request.template_name]["path"]
    template_path = COOKIECUTTER_BASE / template_rel_path

    if not template_path.exists():
        raise HTTPException(
            status_code=404, detail=f"Template directory not found: {template_path}")

    # Create temporary directory for generation
    temp_dir = tempfile.mkdtemp()

    try:
        # Helper to convert values to strings for cookiecutter
        def str_or_empty(val):
            return str(val) if val is not None else ""
        
        # Prepare extra context based on template type
        extra_context = {
            "project_name": str_or_empty(request.project_name),
        }

        # Add template-specific parameters
        if request.template_name == "data":
            extra_context.update({
                "r": str_or_empty(request.r),
                "r_version": str_or_empty(request.r_version),
                "latex": str_or_empty(request.latex),
                "first_name": str_or_empty(request.first_name),
                "last_name": str_or_empty(request.last_name),
                "email": str_or_empty(request.email),
                "institution": str_or_empty(request.institution),
            })
        elif request.template_name in ["article", "presentation"]:
            extra_context.update({
                "first_name": str_or_empty(request.first_name),
                "last_name": str_or_empty(request.last_name),
                "email": str_or_empty(request.email),
                "institution": str_or_empty(request.institution),
            })

        # Generate the project using cookiecutter
        output_dir = cookiecutter(
            str(template_path),
            output_dir=temp_dir,
            no_input=True,
            extra_context=extra_context
        )

        # Create zip file in memory with symlink support
        zip_buffer = io.BytesIO()

        with ZipFile(zip_buffer, 'w') as zip_file:
            # Walk through the generated directory and add files to zip
            output_path = Path(output_dir)
            for file_path in output_path.rglob('*'):
                arcname = str(file_path.relative_to(output_path))
                
                if file_path.is_symlink():
                    # Create a ZipInfo for the symlink
                    zip_info = ZipInfo(arcname)
                    zip_info.create_system = 3  # Unix
                    # Set external attributes to indicate symlink
                    # 0o120000 = symlink file type in Unix
                    # 0o755 = permissions
                    zip_info.external_attr = (0o120000 | 0o755) << 16
                    # Read the symlink target
                    link_target = os.readlink(file_path)
                    zip_file.writestr(zip_info, link_target)
                elif file_path.is_file():
                    # Regular file
                    zip_file.write(file_path, arcname)

        zip_buffer.seek(0)

        # Generate filename
        project_name_safe = (request.project_name or "project").lower().replace(' ', '-')
        filename = f"{request.template_name}-{project_name_safe}.zip"

        # Return the zip file
        return StreamingResponse(
            zip_buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating template: {str(e)}")

    finally:
        # Clean up temporary directory
        shutil.rmtree(temp_dir, ignore_errors=True)


@app.get("/generate")
async def generate_template_get(
    template_name: str = Query(..., description="Template name"),
    project_name: str = Query("My Project", description="Project name"),
    r: bool = Query(True, description="Use R?"),
    r_version: str = Query("4.5.1", description="R version"),
    latex: str = Query("auto", description="LaTeX packages"),
    first_name: str = Query("Morgan", description="First name"),
    last_name: str = Query("Doe", description="Last name"),
    email: str = Query("morgan.doe@example.com", description="Email"),
    institution: str = Query("Your Institution", description="Institution"),
):
    """
    Generate a cookiecutter template using GET parameters (for simple frontend integration).
    Returns a zip file containing the generated project.
    """
    request = TemplateRequest(
        template_name=template_name,
        project_name=project_name,
        r=r,
        r_version=r_version,
        latex=latex,
        first_name=first_name,
        last_name=last_name,
        email=email,
        institution=institution,
    )

    return await generate_template(request)



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

    # Build payload per GitHub API
    payload = {
        "name": body.name,
        "description": body.description,
        "private": body.private,
        "auto_init": False,  # always false, we'll push files ourselves
    }
    if body.gitignore_template:
        payload["gitignore_template"] = body.gitignore_template
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
    main_config_path = COOKIECUTTER_BASE / "cookiecutter.json"
    if not main_config_path.exists():
        raise HTTPException(status_code=500, detail="Template configuration not found")
    with open(main_config_path, 'r') as f:
        main_config = json.load(f)
    if body.template_name not in main_config["templates"]:
        raise HTTPException(status_code=404, detail=f"Template '{body.template_name}' not found")
    template_rel_path = main_config["templates"][body.template_name]["path"]
    template_path = COOKIECUTTER_BASE / template_rel_path
    if not template_path.exists():
        raise HTTPException(status_code=404, detail=f"Template directory not found: {template_path}")

    temp_dir = tempfile.mkdtemp()
    try:
        def str_or_empty(val):
            return str(val) if val is not None else ""
        extra_context = {
            "project_name": str_or_empty(body.project_name or body.name),
        }
        if body.template_name == "data":
            extra_context.update({
                "r": str_or_empty(body.r),
                "r_version": str_or_empty(body.r_version),
                "latex": str_or_empty(body.latex),
                "first_name": str_or_empty(body.first_name),
                "last_name": str_or_empty(body.last_name),
                "email": str_or_empty(body.email),
                "institution": str_or_empty(body.institution),
            })
        elif body.template_name in ["article", "presentation"]:
            extra_context.update({
                "first_name": str_or_empty(body.first_name),
                "last_name": str_or_empty(body.last_name),
                "email": str_or_empty(body.email),
                "institution": str_or_empty(body.institution),
            })

        output_dir = cookiecutter(
            str(template_path),
            output_dir=temp_dir,
            no_input=True,
            extra_context=extra_context
        )

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
from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import URLSafeSerializer


@app.get("/auth/github/login")
async def github_login(request: Request):
    client_id = getattr(settings, 'github_client_id', None)
    redirect_uri = getattr(settings, 'github_redirect_uri', None)
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured (client_id/redirect_uri)")

    # Create a signed state for CSRF protection
    s = URLSafeSerializer(settings.session_secret_key, salt="github-oauth-state")
    state = s.dumps({"nonce": os.urandom(8).hex()})
    request.session["oauth_state"] = state

    authorize_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        "&scope=repo%20read:user"
        f"&state={state}"
    )
    return RedirectResponse(authorize_url)


@app.get("/auth/github/callback")
async def github_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None):
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' parameter")
    # Verify state
    expected = request.session.get("oauth_state")
    if not expected or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    s = URLSafeSerializer(settings.session_secret_key, salt="github-oauth-state")
    try:
        s.loads(state)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    client_id = getattr(settings, 'github_client_id', None)
    client_secret = getattr(settings, 'github_client_secret', None)
    redirect_uri = getattr(settings, 'github_redirect_uri', None)
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=500, detail="GitHub OAuth not configured")

    token_url = "https://github.com/login/oauth/access_token"
    headers = {
        "Accept": "application/json",
    }
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(token_url, headers=headers, data=payload)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"GitHub token exchange failed: {e}")

    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=502, detail=f"GitHub token exchange error: {detail}")

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token returned by GitHub")

    # Store token in session
    request.session["github_token"] = access_token

    # Optionally, fetch user info and store minimal profile
    api_base = getattr(settings, 'github_api_url', 'https://api.github.com').rstrip('/')
    async with httpx.AsyncClient(timeout=30) as client:
        me = await client.get(
            f"{api_base}/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if me.status_code < 400:
        request.session["github_user"] = me.json()

    # Redirect to a simple success page or back to docs
    return RedirectResponse(url="/docs")


@app.get("/auth/github/me")
async def github_me(request: Request):
    token = request.session.get("github_token")
    if not token:
        return JSONResponse(status_code=401, content={"authenticated": False})
    api_base = getattr(settings, 'github_api_url', 'https://api.github.com').rstrip('/')
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{api_base}/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if resp.status_code >= 400:
        return JSONResponse(status_code=resp.status_code, content={"authenticated": False})
    user = resp.json()
    return {"authenticated": True, "user": user}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
