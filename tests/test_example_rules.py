"""Example rules in .schemalock/rules_examples/ work when copied into a rules/ directory.

The validator and the rule are copied into tmp_path; the real files are untouched.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DIR = os.path.join(ROOT, ".schemalock")
EXAMPLES_DIR = os.path.join(REAL_DIR, "rules_examples")
ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

SCHEMA = """model User {
  id    Int    @id @default(autoincrement())
  email String @unique
}
"""

# Valid against the schema, so only the custom rule can make it fail.
CODE = """from prisma import Prisma

prisma = Prisma()
prisma.user.find_first(where={"email": "a@b.c"})
SQL = "%s"
"""


def run_rule(tmp_path, rule, sql):
    """Copy the validator and one example rule into tmp_path, validate code containing `sql`."""
    tool_dir = tmp_path / ".schemalock"
    (tool_dir / "rules").mkdir(parents=True)
    for name in ("ast_validator.py", "schema_parser.py", "rule_loader.py"):
        shutil.copy(os.path.join(REAL_DIR, name), tool_dir / name)
    shutil.copy(os.path.join(EXAMPLES_DIR, rule), tool_dir / "rules" / rule)
    project = tmp_path / "app"
    project.mkdir()
    (project / "schema.prisma").write_text(SCHEMA, encoding="utf-8")
    code_file = project / "main.py"
    code_file.write_text(CODE % sql, encoding="utf-8")
    result = subprocess.run([sys.executable, str(tool_dir / "ast_validator.py"), str(project), str(code_file)],
                            capture_output=True, env=ENV)
    return (result.returncode, result.stdout.decode("utf-8", errors="replace"),
            result.stderr.decode("utf-8", errors="replace"))


def test_no_temp_tables_violation(tmp_path):
    code, out, err = run_rule(tmp_path, "no_temp_tables.py", "create table Temp_users (id int)")
    assert code == 1, out + err
    assert "main.py:5: temp_ tables are not allowed" in out


def test_no_temp_tables_clean(tmp_path):
    code, out, err = run_rule(tmp_path, "no_temp_tables.py", "CREATE TABLE users (id int)")
    assert code == 0, out + err
    assert out.strip() == "OK"


def test_no_drop_table_violation(tmp_path):
    code, out, err = run_rule(tmp_path, "no_drop_table.py", "DROP TABLE users")
    assert code == 1, out + err
    assert "main.py:5: DROP TABLE is not allowed" in out


def test_no_drop_table_lowercase_violation(tmp_path):
    code, out, err = run_rule(tmp_path, "no_drop_table.py", "drop table users")
    assert code == 1, out + err
    assert "main.py:5: DROP TABLE is not allowed" in out


def test_no_drop_table_clean(tmp_path):
    code, out, err = run_rule(tmp_path, "no_drop_table.py", "SELECT * FROM users")
    assert code == 0, out + err
    assert out.strip() == "OK"
