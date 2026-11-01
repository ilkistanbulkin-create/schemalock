"""OpenAPI endpoint tests: run ast_validator.py and hook.py as subprocesses on files in tmp_path."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMALOCK = os.path.join(ROOT, ".schemalock")
VALIDATOR = os.path.join(SCHEMALOCK, "ast_validator.py")
HOOK = os.path.join(SCHEMALOCK, "hook.py")

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

OPENAPI = """\
openapi: 3.0.3
info:
  title: Test API
  version: 1.0.0
paths:
  /users:
    get:
      responses:
        "200":
          description: OK
    post:
      responses:
        "201":
          description: Created
  /users/{id}:
    get:
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: integer
      responses:
        "200":
          description: OK
components:
  schemas:
    User:
      type: object
      properties:
        id:
          type: integer
        email:
          type: string
"""

BROKEN_OPENAPI = """\
openapi: 3.0.3
info:
  title: Broken API
  version: 1.0.0
paths:
  /users:
    get:
      responses:
        "200":
          description: OK
components: [not, a, mapping]
"""


def write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def make_project(tmp_path, code, schema=OPENAPI):
    schema_file = write(tmp_path / "openapi.yaml", schema)
    code_file = write(tmp_path / "client.ts", code)
    return schema_file, code_file


def run_validator(schema_file, code_file):
    result = subprocess.run([sys.executable, VALIDATOR, str(schema_file), str(code_file)],
                            capture_output=True, env=ENV)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def run_hook(project_dir, code_file):
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "cwd": str(project_dir),
        "tool_input": {"file_path": str(code_file)},
    }
    env = dict(ENV, CLAUDE_PROJECT_DIR=str(project_dir))
    result = subprocess.run([sys.executable, HOOK], input=json.dumps(payload).encode("utf-8"),
                            capture_output=True, env=env)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def test_known_path_passes(tmp_path):
    schema_file, code_file = make_project(tmp_path, 'fetch("/users");\n')
    code, output = run_validator(schema_file, code_file)
    assert code == 0, output


def test_unknown_path_fails(tmp_path):
    schema_file, code_file = make_project(tmp_path, 'fetch("/nonexistent");\n')
    code, output = run_validator(schema_file, code_file)
    assert code == 1, output
    assert "/nonexistent" in output


def test_unknown_method_fails(tmp_path):
    schema_file, code_file = make_project(tmp_path, 'fetch("/users", { method: "DELETE" });\n')
    code, output = run_validator(schema_file, code_file)
    assert code == 1, output
    assert "DELETE" in output.upper()


def test_path_template_matches(tmp_path):
    schema_file, code_file = make_project(tmp_path, 'fetch("/users/5", { method: "GET" });\n')
    code, output = run_validator(schema_file, code_file)
    assert code == 0, output


def test_variable_and_absolute_urls_skipped(tmp_path):
    code_text = (
        'const url = "/nonexistent";\n'
        "fetch(url);\n"
        'fetch("https://example.com/nonexistent");\n'
    )
    schema_file, code_file = make_project(tmp_path, code_text)
    code, output = run_validator(schema_file, code_file)
    assert code == 0, output


def test_broken_schema(tmp_path):
    schema_file, code_file = make_project(tmp_path, 'fetch("/users");\n', schema=BROKEN_OPENAPI)
    code, output = run_validator(schema_file, code_file)
    assert code == 3, output
    code, output = run_hook(tmp_path, code_file)
    assert code == 0, output


def test_hook_blocks_wrong_path_with_only_openapi(tmp_path):
    _, code_file = make_project(tmp_path, 'fetch("/nonexistent");\n')
    assert sorted(p.name for p in tmp_path.iterdir()) == ["client.ts", "openapi.yaml"]
    code, output = run_hook(tmp_path, code_file)
    assert code == 2, output
    assert "/nonexistent" in output
