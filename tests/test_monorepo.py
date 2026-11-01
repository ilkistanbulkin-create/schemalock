"""Monorepo with one schema.prisma per app: the schema nearest to the edited file is used,
both by the validator (project dir + file) and the hook."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMALOCK = os.path.join(ROOT, ".schemalock")
VALIDATOR = os.path.join(SCHEMALOCK, "ast_validator.py")
HOOK = os.path.join(SCHEMALOCK, "hook.py")

SCHEMAS = {
    "a": "model User {\n  id    Int    @id\n  email String\n}\n",
    "b": "model User {\n  id       Int    @id\n  userName String\n}\n",
}

CODE = """import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export async function load() {
  return prisma.user.findMany({ where: { %s: "a" } });
}
"""

CASES = [
    # app, column, expected alarm count
    ("a", "email", 0),
    ("b", "email", 1),
    ("b", "userName", 0),
]

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")


def make_project(tmp_path, app, column):
    for name, schema in SCHEMAS.items():
        prisma_dir = tmp_path / "apps" / name / "prisma"
        prisma_dir.mkdir(parents=True)
        (prisma_dir / "schema.prisma").write_text(schema, encoding="utf-8")
    src = tmp_path / "apps" / app / "src"
    src.mkdir()
    code_file = src / "x.ts"
    code_file.write_text(CODE % column, encoding="utf-8")
    return code_file


def alarms(output):
    return [line for line in output.splitlines() if "ERROR:" in line]


@pytest.mark.parametrize("app, column, expected", CASES)
def test_validator(tmp_path, app, column, expected):
    code_file = make_project(tmp_path, app, column)
    result = subprocess.run([sys.executable, VALIDATOR, str(tmp_path), str(code_file)],
                            capture_output=True, env=ENV)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")

    assert len(alarms(output)) == expected, output
    assert result.returncode == (1 if expected else 0), output


@pytest.mark.parametrize("app, column, expected", CASES)
def test_hook(tmp_path, app, column, expected):
    code_file = make_project(tmp_path, app, column)
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "cwd": str(tmp_path),
        "tool_input": {"file_path": str(code_file)},
    }
    result = subprocess.run([sys.executable, HOOK], input=json.dumps(payload).encode("utf-8"),
                            capture_output=True, env=dict(ENV, CLAUDE_PROJECT_DIR=str(tmp_path)))
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")

    assert result.returncode == (2 if expected else 0), stdout + stderr
    assert len(alarms(stderr)) == expected, stdout + stderr
    assert stdout == "", stdout  # no "validation skipped" warning
