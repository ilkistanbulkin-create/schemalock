"""Custom rules in .schemalock/rules/ run after the built-in checks of ast_validator.py.

The validator files are copied into tmp_path (with or without a rules/ directory); the real files are untouched.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DIR = os.path.join(ROOT, ".schemalock")
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

SCHEMA = """model User {
  id    Int    @id @default(autoincrement())
  email String @unique
}
"""

# Valid against the schema, so only custom rules can make it fail.
CODE = """from prisma import Prisma

prisma = Prisma()
prisma.user.find_first(where={"email": "a@b.c"})
print("debug")
"""

NO_PRINT_RULE = """EXTENSIONS = [".py"]

def check(text, checker):
    for n, line in enumerate(text.splitlines(), 1):
        if "print(" in line:
            checker.error(n, "print() is not allowed")
"""

CRASHING_RULE = """EXTENSIONS = [".py"]

def check(text, checker):
    raise RuntimeError("broken rule")
"""

TS_ONLY_RULE = """EXTENSIONS = [".ts"]

def check(text, checker):
    checker.error(1, "ts rule must not run for .py")
"""


def make_project(tmp_path, rules=None):
    """Copy the validator into tmp_path/.schemalock, add rules/ if given; return (validator, project, code_file)."""
    tool_dir = tmp_path / ".schemalock"
    tool_dir.mkdir()
    for name in ("ast_validator.py", "schema_parser.py", "rule_loader.py"):
        shutil.copy(os.path.join(REAL_DIR, name), tool_dir / name)
    if rules is not None:
        (tool_dir / "rules").mkdir()
        for name, body in rules.items():
            (tool_dir / "rules" / name).write_text(body, encoding="utf-8")
    project = tmp_path / "app"
    project.mkdir()
    (project / "schema.prisma").write_text(SCHEMA, encoding="utf-8")
    code_file = project / "main.py"
    code_file.write_text(CODE, encoding="utf-8")
    return tool_dir / "ast_validator.py", project, code_file


def run(validator, project, code_file):
    result = subprocess.run([sys.executable, str(validator), str(project), str(code_file)],
                            capture_output=True, env=ENV)
    return (result.returncode, result.stdout.decode("utf-8", errors="replace"),
            result.stderr.decode("utf-8", errors="replace"))


def test_violating_rule_exits_1(tmp_path):
    code, out, err = run(*make_project(tmp_path, {"no_print.py": NO_PRINT_RULE}))
    assert code == 1, out + err
    assert "main.py:5: print() is not allowed" in out


def test_crashing_rule_does_not_block_others(tmp_path):
    # "a_crash.py" sorts first, so it runs before the rule that reports a violation.
    code, out, err = run(*make_project(tmp_path, {"a_crash.py": CRASHING_RULE,
                                                  "no_print.py": NO_PRINT_RULE}))
    assert code == 1, out + err
    assert "print() is not allowed" in out
    assert "WARNING" in err and "a_crash.py" in err and "broken rule" in err


def test_crashing_rule_alone_keeps_exit_0(tmp_path):
    code, out, err = run(*make_project(tmp_path, {"a_crash.py": CRASHING_RULE}))
    assert code == 0, out + err
    assert "OK" in out
    assert "WARNING" in err


def test_rule_for_other_extension_skipped(tmp_path):
    code, out, err = run(*make_project(tmp_path, {"ts_only.py": TS_ONLY_RULE}))
    assert code == 0, out + err


def test_no_rules_dir_unchanged(tmp_path):
    validator, project, code_file = make_project(tmp_path)
    assert not (validator.parent / "rules").exists()
    code, out, err = run(validator, project, code_file)
    assert code == 0, out + err
    assert out.strip() == "OK"
    assert err == ""

    # Schema violations are still reported as before.
    code_file.write_text(CODE.replace('"email"', '"mail"'), encoding="utf-8")
    code, out, err = run(validator, project, code_file)
    assert code == 1, out + err
    assert "column 'mail' not found" in out
