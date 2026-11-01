"""Hook edge cases: .tsx files are checked, and a validator tool error (exit 3) warns Claude without blocking."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, ".schemalock", "hook.py")

SCHEMA = """model User {
  id    Int    @id @default(autoincrement())
  email String @unique
}
"""

BROKEN_SCHEMA = """model User {
  id    Int    @id @default(autoincrement())
  email String @unique
"""

TSX = """import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export async function UserCard({ id }: { id: number }) {
  const user = await prisma.user.findFirst({ where: { userId: id } });
  return <div>{user?.email}</div>;
}
"""


def run_hook(project_dir, code_file):
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "cwd": str(project_dir),
        "tool_input": {"file_path": str(code_file)},
    }
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
               CLAUDE_PROJECT_DIR=str(project_dir))
    result = subprocess.run([sys.executable, HOOK], input=json.dumps(payload).encode("utf-8"),
                            capture_output=True, env=env)
    return (result.returncode, result.stdout.decode("utf-8", errors="replace"),
            result.stderr.decode("utf-8", errors="replace"))


def test_hook_blocks_wrong_field_in_tsx(tmp_path):
    (tmp_path / "schema.prisma").write_text(SCHEMA, encoding="utf-8")
    code_file = tmp_path / "UserCard.tsx"
    code_file.write_text(TSX, encoding="utf-8")

    code, stdout, stderr = run_hook(tmp_path, code_file)
    assert code == 2, stdout + stderr
    assert "userId" in stderr


def test_hook_warns_on_broken_schema(tmp_path):
    (tmp_path / "schema.prisma").write_text(BROKEN_SCHEMA, encoding="utf-8")
    code_file = tmp_path / "UserCard.tsx"
    code_file.write_text(TSX, encoding="utf-8")

    code, stdout, stderr = run_hook(tmp_path, code_file)
    assert code == 0, stdout + stderr
    assert "SchemaLock" in stdout
    assert "additionalContext" in stdout
    context = json.loads(stdout)["hookSpecificOutput"]
    assert context["hookEventName"] == "PostToolUse"
    assert context["additionalContext"].startswith("SchemaLock: validation skipped, reason: ")
    assert "missing a closing" in context["additionalContext"]
