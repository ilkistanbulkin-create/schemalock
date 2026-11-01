"""schema.prisma and openapi.yaml in the same project: Prisma calls are checked against the
Prisma schema and HTTP calls against the OpenAPI schema, both by the validator and the hook."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMALOCK = os.path.join(ROOT, ".schemalock")
VALIDATOR = os.path.join(SCHEMALOCK, "ast_validator.py")
HOOK = os.path.join(SCHEMALOCK, "hook.py")

PRISMA = """model User {
  id    Int    @id @default(autoincrement())
  email String @unique
}
"""

# No User model in components/schemas: the Prisma check must not depend on the OpenAPI file.
OPENAPI = """openapi: 3.0.0
info:
  title: Test
  version: "1.0"
paths:
  /users:
    get:
      responses:
        "200":
          description: ok
"""

CODE = """import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export async function load() {
  const user = await prisma.user.findFirst({ where: { %s: "a@b.c" } });
  const res = await fetch("%s");
  return [user, res];
}
"""

CASES = [
    # column, url, expected alarm count
    ("emial", "/users", 1),   # wrong Prisma column
    ("email", "/userz", 1),   # wrong HTTP path
    ("email", "/users", 0),   # both correct
]

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")


def make_project(tmp_path, column, url):
    (tmp_path / "schema.prisma").write_text(PRISMA, encoding="utf-8")
    (tmp_path / "openapi.yaml").write_text(OPENAPI, encoding="utf-8")
    code_file = tmp_path / "app.ts"
    code_file.write_text(CODE % (column, url), encoding="utf-8")
    return code_file


def alarms(output):
    return [line for line in output.splitlines() if "ERROR:" in line]


@pytest.mark.parametrize("column, url, expected", CASES)
def test_validator(tmp_path, column, url, expected):
    code_file = make_project(tmp_path, column, url)
    result = subprocess.run([sys.executable, VALIDATOR, str(tmp_path), str(code_file)],
                            capture_output=True, env=ENV)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")

    assert len(alarms(output)) == expected, output
    assert result.returncode == (1 if expected else 0), output


@pytest.mark.parametrize("column, url, expected", CASES)
def test_hook(tmp_path, column, url, expected):
    code_file = make_project(tmp_path, column, url)
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
