"""Prisma count: `_all` is a valid key in count's select; other unknown keys still are not."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR = os.path.join(ROOT, ".schemalock", "ast_validator.py")

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

SCHEMA = """\
model User {
  id    Int    @id @default(autoincrement())
  email String @unique
}
"""


def run_validator(tmp_path, filename, code):
    schema_file = tmp_path / "schema.prisma"
    schema_file.write_text(SCHEMA, encoding="utf-8")
    code_file = tmp_path / filename
    code_file.write_text(code, encoding="utf-8")
    result = subprocess.run([sys.executable, VALIDATOR, str(schema_file), str(code_file)],
                            capture_output=True, env=ENV)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def alarms(output):
    return [line for line in output.splitlines() if line.startswith("ERROR:")]


def test_count_select_all_is_valid(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 "const n = await prisma.user.count({ select: { _all: true } });\n")
    assert code == 0, output
    assert alarms(output) == [], output


def test_count_select_unknown_field_is_flagged(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 "const n = await prisma.user.count({ select: { nonexistentField: true } });\n")
    assert code != 0, output
    assert len(alarms(output)) == 1, output
    assert "nonexistentField" in output
