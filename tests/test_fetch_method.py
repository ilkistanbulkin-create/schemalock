"""fetch() with a method that comes from a variable: only the path is checked, not GET."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR = os.path.join(ROOT, ".schemalock", "ast_validator.py")

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

# /users only has POST
OPENAPI = """\
openapi: 3.0.3
info:
  title: Test API
  version: 1.0.0
paths:
  /users:
    post:
      responses:
        "201":
          description: Created
"""


def run_validator(tmp_path, code):
    schema_file = tmp_path / "openapi.yaml"
    schema_file.write_text(OPENAPI, encoding="utf-8")
    code_file = tmp_path / "client.ts"
    code_file.write_text(code, encoding="utf-8")
    result = subprocess.run([sys.executable, VALIDATOR, str(schema_file), str(code_file)],
                            capture_output=True, env=ENV)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def test_variable_method_on_known_path_passes(tmp_path):
    code, output = run_validator(tmp_path, 'const m = "POST";\nfetch("/users", { method: m });\n')
    assert code == 0, output


def test_variable_method_on_unknown_path_fails(tmp_path):
    code, output = run_validator(tmp_path, 'const m = "POST";\nfetch("/nonexistent", { method: m });\n')
    assert code == 1, output
    assert "/nonexistent" in output


def test_options_variable_on_known_path_passes(tmp_path):
    code, output = run_validator(tmp_path, 'fetch("/users", opts);\n')
    assert code == 0, output


def test_options_variable_on_unknown_path_fails(tmp_path):
    code, output = run_validator(tmp_path, 'fetch("/nonexistent", opts);\n')
    assert code == 1, output
    assert "/nonexistent" in output


def test_options_spread_on_known_path_passes(tmp_path):
    code, output = run_validator(tmp_path, 'fetch("/users", { ...opts });\n')
    assert code == 0, output


def test_literal_get_still_fails(tmp_path):
    code, output = run_validator(tmp_path, 'fetch("/users", { method: "GET" });\n')
    assert code == 1, output
    assert "GET" in output
