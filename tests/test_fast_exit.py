"""Fast exit: a file with no query skips the schema checks, but custom rules still run.

The hook and validator files are copied into tmp_path (with an optional rules/ directory);
the real files are untouched.
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DIR = os.path.join(ROOT, ".schemalock")
sys.path.insert(0, REAL_DIR)
sys.dont_write_bytecode = True

import ast_validator  # noqa: E402

SCHEMA = """model User {
  id    Int    @id @default(autoincrement())
  email String @unique
}
"""

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

NO_QUERY_TSX = """import { useState } from "react";

export function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(count + 1)}>{count}</button>;
}
"""

WRONG_FIELD_TSX = """import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export async function UserCard({ id }: { id: number }) {
  const user = await prisma.user.findFirst({ where: { userId: id } });
  return <div>{user?.email}</div>;
}
"""

# Custom client name: the file never says `prisma.` before the query.
WRONG_FIELD_PY = """from prisma import Prisma

db = Prisma()
db.user.find_first(where={"mail": "a@b.c"})
"""

WRONG_PATH_TSX = """export async function load() {
  const res = await fetch("/userz");
  return res.json();
}
"""

NO_USE_STATE_RULE = """EXTENSIONS = [".tsx"]

def check(text, checker):
    for n, line in enumerate(text.splitlines(), 1):
        if "useState" in line:
            checker.error(n, "useState is not allowed here")
"""


def make_project(tmp_path, schemas, rules=None):
    """Copy hook + validator into tmp_path/.schemalock, write schemas; return (hook, project)."""
    tool_dir = tmp_path / ".schemalock"
    tool_dir.mkdir()
    for name in ("hook.py", "ast_validator.py", "schema_parser.py", "rule_loader.py"):
        shutil.copy(os.path.join(REAL_DIR, name), tool_dir / name)
    if rules is not None:
        (tool_dir / "rules").mkdir()
        for name, body in rules.items():
            (tool_dir / "rules" / name).write_text(body, encoding="utf-8")
    project = tmp_path / "app"
    project.mkdir()
    for name, body in schemas.items():
        (project / name).write_text(body, encoding="utf-8")
    return tool_dir / "hook.py", project


def run_hook(hook, project, code_file):
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "cwd": str(project),
        "tool_input": {"file_path": str(code_file)},
    }
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
               CLAUDE_PROJECT_DIR=str(project))
    result = subprocess.run([sys.executable, str(hook)], input=json.dumps(payload).encode("utf-8"),
                            capture_output=True, env=env)
    return (result.returncode, result.stdout.decode("utf-8", errors="replace"),
            result.stderr.decode("utf-8", errors="replace"))


def test_no_query_tsx_fast_exit(tmp_path, monkeypatch, capsys):
    hook, project = make_project(tmp_path, {"schema.prisma": SCHEMA, "openapi.yaml": OPENAPI})
    code_file = project / "Counter.tsx"
    code_file.write_text(NO_QUERY_TSX, encoding="utf-8")

    code, out, err = run_hook(hook, project, code_file)
    assert code == 0, out + err
    assert out == "" and err == ""

    # In-process: the schema checks are not run at all.
    def must_not_run(*_):
        raise AssertionError("schema check ran on a file without queries")
    for name in ("check_js", "check_js_http", "check_python", "check_python_http"):
        monkeypatch.setattr(ast_validator, name, must_not_run)
    monkeypatch.setattr(ast_validator, "RULES_DIR", str(tmp_path / "no_rules"))
    assert ast_validator.main(["ast_validator.py", str(project), str(code_file)]) == 0
    assert capsys.readouterr().out.strip() == "OK"


def test_wrong_prisma_field_still_caught(tmp_path):
    hook, project = make_project(tmp_path, {"schema.prisma": SCHEMA})
    tsx = project / "UserCard.tsx"
    tsx.write_text(WRONG_FIELD_TSX, encoding="utf-8")
    code, out, err = run_hook(hook, project, tsx)
    assert code == 2, out + err
    assert "column 'userId' not found" in err

    py = project / "users.py"
    py.write_text(WRONG_FIELD_PY, encoding="utf-8")
    code, out, err = run_hook(hook, project, py)
    assert code == 2, out + err
    assert "column 'mail' not found" in err


def test_wrong_fetch_path_still_caught(tmp_path):
    hook, project = make_project(tmp_path, {"openapi.yaml": OPENAPI})
    code_file = project / "load.tsx"
    code_file.write_text(WRONG_PATH_TSX, encoding="utf-8")
    code, out, err = run_hook(hook, project, code_file)
    assert code == 2, out + err
    assert "'/userz' path not found" in err


def test_custom_rule_runs_on_no_query_file(tmp_path):
    hook, project = make_project(tmp_path, {"schema.prisma": SCHEMA},
                                 rules={"no_use_state.py": NO_USE_STATE_RULE})
    code_file = project / "Counter.tsx"
    code_file.write_text(NO_QUERY_TSX, encoding="utf-8")
    code, out, err = run_hook(hook, project, code_file)
    assert code == 2, out + err
    assert "Counter.tsx:4: useState is not allowed here" in err
