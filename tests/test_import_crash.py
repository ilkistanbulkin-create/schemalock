"""An import-time crash in ast_validator.py exits 3 (tool error), and the hook warns instead of blocking.

The validator and hook are copied into tmp_path next to a broken schema_parser.py; the real files are untouched.
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DIR = os.path.join(ROOT, ".schemalock")

SCHEMA = """model User {
  id    Int    @id @default(autoincrement())
  email String @unique
}
"""

# Wrong field on purpose: if the validator ran, this would be a violation (exit 1 / hook exit 2).
CODE = """from prisma import Prisma

prisma = Prisma()
prisma.user.find_first(where={"userId": 1})
"""

# Enough for hook.py's import, but parse_prisma / parse_openapi are missing, so the validator's import fails.
STUB_SCHEMA_PARSER = """import os

SCHEMA_FILENAMES = ("schema.prisma",)


class SchemaError(Exception):
    pass


def find_schema(project_dir, filenames):
    path = os.path.join(project_dir, "schema.prisma")
    if os.path.isfile(path):
        return path
    raise SchemaError("schema.prisma not found")
"""

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")


def make_project(tmp_path, schema_parser_source):
    tool_dir = tmp_path / ".schemalock"
    tool_dir.mkdir()
    shutil.copy(os.path.join(REAL_DIR, "ast_validator.py"), tool_dir)
    shutil.copy(os.path.join(REAL_DIR, "hook.py"), tool_dir)
    if schema_parser_source is not None:
        (tool_dir / "schema_parser.py").write_text(schema_parser_source, encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / "schema.prisma").write_text(SCHEMA, encoding="utf-8")
    code_file = project / "app.py"
    code_file.write_text(CODE, encoding="utf-8")
    return tool_dir, project, code_file


def run_validator(tool_dir, project, code_file):
    result = subprocess.run([sys.executable, str(tool_dir / "ast_validator.py"), str(project), str(code_file)],
                            capture_output=True, env=ENV)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def test_missing_module_exits_3(tmp_path):
    tool_dir, project, code_file = make_project(tmp_path, None)  # no schema_parser.py at all

    code, output = run_validator(tool_dir, project, code_file)
    assert code == 3, output
    assert "schema_parser" in output


def test_missing_name_exits_3(tmp_path):
    tool_dir, project, code_file = make_project(tmp_path, STUB_SCHEMA_PARSER)

    code, output = run_validator(tool_dir, project, code_file)
    assert code == 3, output
    assert "ImportError" in output


def test_hook_warns_without_blocking(tmp_path):
    tool_dir, project, code_file = make_project(tmp_path, STUB_SCHEMA_PARSER)
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "cwd": str(project),
        "tool_input": {"file_path": str(code_file)},
    }
    result = subprocess.run([sys.executable, str(tool_dir / "hook.py")],
                            input=json.dumps(payload).encode("utf-8"), capture_output=True,
                            env=dict(ENV, CLAUDE_PROJECT_DIR=str(project)))
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")

    assert result.returncode != 2, stdout + stderr
    assert result.returncode == 0, stdout + stderr
    context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
    assert "validation skipped" in context
    assert "ImportError" in context
