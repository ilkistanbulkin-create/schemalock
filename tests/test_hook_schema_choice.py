"""Hook and manual command must pick the same schema: schema.prisma at the root and in prisma/."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMALOCK = os.path.join(ROOT, ".schemalock")
VALIDATOR = os.path.join(SCHEMALOCK, "ast_validator.py")
HOOK = os.path.join(SCHEMALOCK, "hook.py")

ROOT_SCHEMA = """model User {
  id    Int    @id @default(autoincrement())
  email String @unique
}
"""

PRISMA_DIR_SCHEMA = """model User {
  id     Int @id @default(autoincrement())
  userId Int @unique
}
"""

CODE = """import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export async function findUser(value: number) {
  return prisma.user.findFirst({ where: { %s: value } });
}
"""

# Validator exit code -> hook exit code (violations block with 2, everything else is 0).
HOOK_CODE = {0: 0, 1: 2}


def make_project(tmp_path, column):
    (tmp_path / "schema.prisma").write_text(ROOT_SCHEMA, encoding="utf-8")
    (tmp_path / "prisma").mkdir()
    (tmp_path / "prisma" / "schema.prisma").write_text(PRISMA_DIR_SCHEMA, encoding="utf-8")
    code_file = tmp_path / "prisma" / "seed.ts"
    code_file.write_text(CODE % column, encoding="utf-8")
    return code_file


def env_for(project_dir):
    return dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                CLAUDE_PROJECT_DIR=str(project_dir))


def run_manual(project_dir, code_file):
    result = subprocess.run([sys.executable, VALIDATOR, str(project_dir), str(code_file)],
                            capture_output=True, env=env_for(project_dir))
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def run_hook(project_dir, code_file):
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "cwd": str(project_dir),
        "tool_input": {"file_path": str(code_file)},
    }
    result = subprocess.run([sys.executable, HOOK], input=json.dumps(payload).encode("utf-8"),
                            capture_output=True, env=env_for(project_dir))
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


@pytest.mark.parametrize("column, manual_code", [("email", 1), ("userId", 0)])
def test_hook_and_manual_pick_same_schema(tmp_path, column, manual_code):
    code_file = make_project(tmp_path, column)

    m_code, m_out = run_manual(tmp_path, code_file)
    h_code, h_out = run_hook(tmp_path, code_file)

    assert m_code == manual_code, m_out  # nearest schema to the edited file: prisma/schema.prisma for prisma/seed.ts
    assert h_code == HOOK_CODE[m_code], f"manual={m_code}\n{m_out}\nhook={h_code}\n{h_out}"
    if manual_code == 1:
        assert "userId" in m_out and "userId" in h_out
