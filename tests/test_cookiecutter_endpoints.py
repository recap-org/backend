from __future__ import annotations

import io
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.main import app
import app.cookiecutter as cc_mod


@pytest.fixture()
def client():
    return TestClient(app)


def _stub_templates_index() -> Dict[str, Any]:
    return {
        "templates": {
            "article": {
                "path": "article",
                "title": "Article",
                "description": "Academic article template",
            }
        }
    }


def test_list_templates_ok(client, monkeypatch):
    monkeypatch.setattr(cc_mod, "_load_main_config",
                        lambda: _stub_templates_index())

    r = client.get("/cookiecutter")
    assert r.status_code == 200
    data = r.json()
    assert "templates" in data
    assert "article" in data["templates"]
    assert data["templates"]["article"]["title"] == "Article"


def test_get_template_config_ok(client, monkeypatch):
    expected_cfg = {"project_name": "Demo", "license": ["MIT", "BSD-3-Clause"]}
    monkeypatch.setattr(cc_mod, "_load_template_config",
                        lambda name: expected_cfg)

    r = client.get("/cookiecutter/article")
    assert r.status_code == 200
    assert r.json() == expected_cfg


def test_download_generates_zip_with_slug_filename(client):
    # Use real template config and real cookiecutter generation for the lean 'article' template
    body = {"project_name": "My Project"}
    r = client.post("/cookiecutter/article/download", json=body)

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    cd = r.headers.get("content-disposition", "")
    assert 'filename="my-project.zip"' in cd
    # We don't know exact bytes, but the ZIP should be non-empty
    assert isinstance(r.content, (bytes, bytearray)) and len(r.content) > 100


def test_download_type_mismatch_returns_400(client, monkeypatch):
    # version default is a string; sending an int should fail in _build_extra_context_from_template
    template_cfg = {"project_name": "Demo", "r_version": True}
    monkeypatch.setattr(cc_mod, "_load_template_config",
                        lambda name: template_cfg)
    # Prevent real generation
    monkeypatch.setattr(cc_mod, "cookiecutter", lambda *a, **k: "/tmp/nowhere")
    monkeypatch.setattr(cc_mod, "zip_directory_with_symlinks",
                        lambda *_: io.BytesIO())

    r = client.post("/cookiecutter/data/download", json={"r_version": 2})
    assert r.status_code == 400
    assert "Type mismatch for template parameter 'r_version'" in r.json().get("detail", "")


@pytest.mark.usefixtures("respx_mock")
def test_github_repo_success_user(client, monkeypatch, respx_mock):
    # Arrange: mock GitHub API create repo
    api_url = "https://api.github.com/user/repos"
    github_resp = {
        "id": 123,
        "name": "my-repo",
        "full_name": "user/my-repo",
        "private": True,
        "html_url": "https://github.com/user/my-repo",
        "ssh_url": "git@github.com:user/my-repo.git",
        "clone_url": "https://github.com/user/my-repo.git",
        "default_branch": "main",
        "description": None,
        "visibility": "private",
    }
    respx_mock.post(api_url).respond(201, json=github_resp)

    # Stub template defaults
    monkeypatch.setattr(cc_mod, "_load_template_config",
                        lambda name: {"project_name": "Demo"})

    # Prepare a temp repo directory to return from cookiecutter
    tmpdir = tempfile.TemporaryDirectory()
    repo_path = Path(tmpdir.name) / "my-repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / "README.md").write_text("# Test Repo\n")
    monkeypatch.setattr(cc_mod, "cookiecutter", lambda *a, **k: str(repo_path))

    # Fake subprocess.run to always succeed
    def fake_run(*args, **kwargs):
        # Imitate subprocess.CompletedProcess minimal surface
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cc_mod.subprocess, "run", fake_run)

    body = {"project_name": "My Repo", "description": "desc"}
    r = client.post(
        "/cookiecutter/article/github",
        json=body,
        headers={"Authorization": "Bearer token-abc"},
    )

    assert r.status_code == 200
    data = r.json()
    assert data["id"] == 123
    assert data["name"] == "my-repo"
    assert data["default_branch"] == "main"
    assert data["clone_url"] == "https://github.com/user/my-repo.git"

    tmpdir.cleanup()


@pytest.mark.usefixtures("respx_mock")
def test_github_repo_missing_token_401(client, monkeypatch):
    # Ensure env var is not used accidentally
    if "GITHUB_TOKEN" in os.environ:
        del os.environ["GITHUB_TOKEN"]

    monkeypatch.setattr(cc_mod, "_load_template_config",
                        lambda name: {"project_name": "Demo"})
    r = client.post("/cookiecutter/article/github", json={"project_name": "X"})

    assert r.status_code == 401
    assert "Missing GitHub token" in r.json().get("detail", "")


@pytest.mark.usefixtures("respx_mock")
def test_github_repo_github_error_422(client, monkeypatch, respx_mock):
    respx_mock.post("https://api.github.com/user/repos").respond(
        422, json={"message": "Validation Failed", "errors": [{"resource": "Repo", "field": "name", "code": "custom"}]}
    )
    monkeypatch.setattr(cc_mod, "_load_template_config",
                        lambda name: {"project_name": "Demo"})

    r = client.post(
        "/cookiecutter/article/github",
        json={"project_name": "Bad Name"},
        headers={"Authorization": "Bearer token-abc"},
    )

    assert r.status_code == 422
    assert "Validation Failed" in r.json().get("detail", "")


@pytest.mark.usefixtures("respx_mock")
def test_github_repo_push_failure_500(client, monkeypatch, respx_mock):
    # Mock successful repo creation
    respx_mock.post("https://api.github.com/user/repos").respond(201, json={
        "id": 1,
        "name": "my-repo",
        "full_name": "user/my-repo",
        "private": True,
        "html_url": "https://github.com/user/my-repo",
        "ssh_url": "git@github.com:user/my-repo.git",
        "clone_url": "https://github.com/user/my-repo.git",
        "default_branch": "main",
    })

    # Stub template
    monkeypatch.setattr(cc_mod, "_load_template_config",
                        lambda name: {"project_name": "Demo"})

    # Cookiecutter returns an existing dir
    tmpdir = tempfile.TemporaryDirectory()
    repo_path = Path(tmpdir.name) / "my-repo"
    repo_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cc_mod, "cookiecutter", lambda *a, **k: str(repo_path))

    # Fake subprocess.run that fails on push
    def fake_run(cmd, *a, **kw):
        if isinstance(cmd, (list, tuple)) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "push":
            return SimpleNamespace(returncode=1, stdout="", stderr="rejected")
        # Simulate check=True raising only if non-zero; since we always return 0 here it's fine
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cc_mod.subprocess, "run", fake_run)

    r = client.post(
        "/cookiecutter/article/github",
        json={"project_name": "My Repo"},
        headers={"Authorization": "Bearer token-abc"},
    )

    assert r.status_code == 500
    assert "Git push failed" in r.json().get("detail", "")
