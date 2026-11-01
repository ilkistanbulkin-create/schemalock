"""OpenAPI endpoint false positives: servers base path, static files and framework routes.

Runs ast_validator.py as a subprocess on files in tmp_path.
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR = os.path.join(ROOT, ".schemalock", "ast_validator.py")

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

OPENAPI = """\
openapi: 3.0.3
info:
  title: Test API
  version: 1.0.0
servers:
  - url: /api/v1
paths:
  /users:
    get:
      responses:
        "200":
          description: OK
"""


def run_validator(tmp_path, code):
    (tmp_path / "openapi.yaml").write_text(OPENAPI, encoding="utf-8")
    code_file = tmp_path / "app.ts"
    code_file.write_text(code, encoding="utf-8")
    return subprocess.run(
        [sys.executable, VALIDATOR, str(tmp_path / "openapi.yaml"), str(code_file)],
        capture_output=True, text=True, encoding="utf-8", env=ENV,
    )


@pytest.mark.parametrize("url", ["/api/v1/users", "/users"])
def test_base_path_both_spellings_ok(tmp_path, url):
    result = run_validator(tmp_path, f'fetch("{url}");\n')
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("url", ["/logo.png", "/_next/static/x.js", "/api/auth/session"])
def test_static_and_framework_paths_skipped(tmp_path, url):
    result = run_validator(tmp_path, f'fetch("{url}");\n')
    assert result.returncode == 0, result.stdout + result.stderr


def test_unknown_path_still_fails(tmp_path):
    result = run_validator(tmp_path, 'fetch("/no-such-path");\n')
    assert result.returncode == 1, result.stdout + result.stderr
    assert "/no-such-path" in result.stdout
