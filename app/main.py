"""
FastAPI backend for dynamically generating and serving cookiecutter templates.
"""
import os
import json
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from zipfile import ZipFile
import io

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from cookiecutter.main import cookiecutter

try:
    from .config import settings
except ImportError:
    # Fallback for running directly
    settings = type('Settings', (), {
        'app_name': 'Recap Template API',
        'app_version': '1.0.0',
        'allowed_origins': ['*'],
        'cookiecutter_base_path': 'cookiecutter'
    })()


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
            "/generate": "Generate and download a template"
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
        # Prepare extra context based on template type
        extra_context = {
            "project_name": request.project_name,
        }

        # Add template-specific parameters
        if request.template_name == "data":
            extra_context.update({
                "r": request.r,
                "r_version": request.r_version,
                "latex": request.latex,
                "first_name": request.first_name,
                "last_name": request.last_name,
                "email": request.email,
                "institution": request.institution,
            })
        elif request.template_name in ["article", "presentation"]:
            extra_context.update({
                "first_name": request.first_name,
                "last_name": request.last_name,
                "email": request.email,
                "institution": request.institution,
            })

        # Generate the project using cookiecutter
        output_dir = cookiecutter(
            str(template_path),
            output_dir=temp_dir,
            no_input=True,
            extra_context=extra_context
        )

        # Create zip file in memory
        zip_buffer = io.BytesIO()

        with ZipFile(zip_buffer, 'w') as zip_file:
            # Walk through the generated directory and add files to zip
            output_path = Path(output_dir)
            for file_path in output_path.rglob('*'):
                if file_path.is_file():
                    # Calculate relative path for the archive
                    arcname = file_path.relative_to(output_path)
                    zip_file.write(file_path, arcname)

        zip_buffer.seek(0)

        # Generate filename
        filename = f"{request.template_name}-{request.project_name.lower().replace(' ', '-')}.zip"

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
