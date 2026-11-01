"""Prisma view blocks are read like model blocks: prisma.userInfo must not be reported as an unknown model."""
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

view UserInfo {
  id    Int
  email String
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


def test_view_valid_column(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 'await prisma.userInfo.findMany({ where: { email: "a" } });\n')
    assert code == 0, output


def test_view_invalid_column(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 'await prisma.userInfo.findMany({ where: { emial: "a" } });\n')
    assert code == 1, output
    assert "emial" in output
