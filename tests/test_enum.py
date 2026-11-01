"""Prisma enum values: string literals given to enum-typed columns must be valid enum values."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR = os.path.join(ROOT, ".schemalock", "ast_validator.py")

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

SCHEMA = """\
enum Role {
  USER
  ADMIN
}

model User {
  id    Int    @id @default(autoincrement())
  email String @unique
  role  Role   @default(USER)
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


def test_ts_valid_enum_value(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 'await prisma.user.create({ data: { email: "a@b.c", role: "ADMIN" } });\n')
    assert code == 0, output


def test_ts_invalid_enum_value(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 'await prisma.user.create({ data: { email: "a@b.c", role: "BOSS" } });\n')
    assert code == 1, output
    assert "BOSS" in output
    assert "USER" in output and "ADMIN" in output


def test_ts_invalid_enum_value_in_where(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 'await prisma.user.findMany({ where: { role: "BOSS" } });\n')
    assert code == 1, output
    assert "BOSS" in output


def test_python_invalid_enum_value(tmp_path):
    code, output = run_validator(tmp_path, "app.py",
                                 'prisma.user.create(data={"email": "a@b.c", "role": "BOSS"})\n')
    assert code == 1, output
    assert "BOSS" in output
    assert "USER" in output and "ADMIN" in output


def test_python_valid_enum_value(tmp_path):
    code, output = run_validator(tmp_path, "app.py",
                                 'prisma.user.find_many(where={"role": "USER"})\n')
    assert code == 0, output


def test_variable_and_complex_values_are_skipped(tmp_path):
    code, output = run_validator(tmp_path, "app.ts", (
        "const r = getRole();\n"
        'await prisma.user.create({ data: { email: "a@b.c", role: r } });\n'
        'await prisma.user.findMany({ where: { role: { in: ["BOSS"] } } });\n'
    ))
    assert code == 0, output
