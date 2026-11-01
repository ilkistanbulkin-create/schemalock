"""Run ast_validator.py as a subprocess on small Python / TypeScript files written to tmp_path."""
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
  name  String?
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


def test_python_prisma_types_is_not_a_model(tmp_path):
    code, output = run_validator(tmp_path, "app.py", (
        "import prisma\n"
        "data = prisma.types.UserCreateInput(email='a@b.c')\n"
        "err = prisma.errors.UniqueViolationError('x')\n"
        "role = prisma.enums.Role('ADMIN')\n"
    ))
    assert code == 0, output


def test_python_unknown_model_still_caught(tmp_path):
    code, output = run_validator(tmp_path, "app.py", "prisma.nonexistent.find_many()\n")
    assert code == 1, output
    assert "nonexistent" in output


def test_ts_bracket_accessor_unknown_column(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 "await prisma['user'].findMany({ where: { userId: 1 } });\n")
    assert code == 1, output
    assert "userId" in output


def test_ts_bracket_accessor_double_quotes_unknown_model(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 'await prisma["nonexistent"].findMany({ where: { id: 1 } });\n')
    assert code == 1, output
    assert "nonexistent" in output


def test_ts_bracket_accessor_valid(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 'await prisma["user"].findMany({ where: { email: "a@b.c" } });\n')
    assert code == 0, output


def test_python_assigned_client_unknown_column(tmp_path):
    code, output = run_validator(tmp_path, "app.py", (
        "from prisma import Prisma\n"
        "db = Prisma()\n"
        "db.user.find_many(where={'userId': 1})\n"
    ))
    assert code == 1, output
    assert "userId" in output


def test_python_assigned_client_valid(tmp_path):
    code, output = run_validator(tmp_path, "app.py", (
        "from prisma import Prisma\n"
        "db = Prisma()\n"
        "db.user.find_many(where={'id': 1})\n"
    ))
    assert code == 0, output


def test_python_async_with_client_unknown_model(tmp_path):
    code, output = run_validator(tmp_path, "app.py", (
        "from prisma import Prisma\n"
        "async def main():\n"
        "    async with Prisma() as db:\n"
        "        await db.nonexistent.find_many()\n"
    ))
    assert code == 1, output
    assert "nonexistent" in output


def test_python_unrelated_db_name_ignored(tmp_path):
    code, output = run_validator(tmp_path, "app.py", (
        "db = {}\n"
        "db.nonexistent.find_many(where={'userId': 1})\n"
    ))
    assert code == 0, output
