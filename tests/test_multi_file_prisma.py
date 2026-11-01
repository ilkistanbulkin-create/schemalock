"""Multi-file Prisma schema: every .prisma file in prisma/schema/ is read as one schema, both by
the validator and the hook."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMALOCK = os.path.join(ROOT, ".schemalock")
VALIDATOR = os.path.join(SCHEMALOCK, "ast_validator.py")
HOOK = os.path.join(SCHEMALOCK, "hook.py")

BASE = """datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

generator client {
  provider = "prisma-client-js"
}
"""

USER = """model User {
  id    Int    @id @default(autoincrement())
  email String @unique
  posts Post[]
}
"""

POST = """model Post {
  id       Int    @id @default(autoincrement())
  title    String
  authorId Int
  author   User   @relation(fields: [authorId], references: [id])
}
"""

CODE = """import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export async function load() {
  const user = await prisma.user.findFirst({ where: { %s: "a@b.c" } });
  const posts = await prisma.post.findMany({ where: { %s: "x" } });
  return [user, posts];
}
"""

CASES = [
    # user column, post column, expected alarm count
    ("email", "title", 0),   # both correct
    ("emial", "title", 1),   # wrong User column
    ("email", "titel", 1),   # wrong Post column
]

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")


def make_project(tmp_path, user_column, post_column):
    schema_dir = tmp_path / "prisma" / "schema"
    schema_dir.mkdir(parents=True)
    (schema_dir / "schema.prisma").write_text(BASE, encoding="utf-8")
    (schema_dir / "user.prisma").write_text(USER, encoding="utf-8")
    (schema_dir / "post.prisma").write_text(POST, encoding="utf-8")
    code_file = tmp_path / "app.ts"
    code_file.write_text(CODE % (user_column, post_column), encoding="utf-8")
    return code_file


def alarms(output):
    return [line for line in output.splitlines() if "ERROR:" in line]


@pytest.mark.parametrize("user_column, post_column, expected", CASES)
def test_validator(tmp_path, user_column, post_column, expected):
    code_file = make_project(tmp_path, user_column, post_column)
    result = subprocess.run([sys.executable, VALIDATOR, str(tmp_path), str(code_file)],
                            capture_output=True, env=ENV)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")

    assert len(alarms(output)) == expected, output
    assert result.returncode == (1 if expected else 0), output


@pytest.mark.parametrize("user_column, post_column, expected", CASES)
def test_hook(tmp_path, user_column, post_column, expected):
    code_file = make_project(tmp_path, user_column, post_column)
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
