"""BOM tests: schema and code files written with a UTF-8 BOM (utf-8-sig) must validate like plain UTF-8."""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR = os.path.join(ROOT, ".schemalock", "ast_validator.py")

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

PRISMA = """\
model User {
  id    Int    @id @default(autoincrement())
  email String @unique
  name  String?
}
"""

OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {"/users": {"get": {"responses": {"200": {"description": "OK"}}}}},
}


def write_bom(path, text):
    path.write_text(text, encoding="utf-8-sig")
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    return path


def run_validator(schema_file, code_file):
    result = subprocess.run([sys.executable, VALIDATOR, str(schema_file), str(code_file)],
                            capture_output=True, env=ENV)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def test_bom_prisma_schema_recognizes_user(tmp_path):
    schema_file = write_bom(tmp_path / "schema.prisma", PRISMA)
    code_file = (tmp_path / "app.ts")
    code_file.write_text('await prisma.user.findMany({ where: { email: "a@b.c" } });\n', encoding="utf-8")
    code, output = run_validator(schema_file, code_file)
    assert code == 0, output


def test_bom_python_code_unknown_column(tmp_path):
    schema_file = tmp_path / "schema.prisma"
    schema_file.write_text(PRISMA, encoding="utf-8")
    code_file = write_bom(tmp_path / "app.py", (
        "from prisma import Prisma\n"
        "db = Prisma()\n"
        "db.user.find_many(where={'userId': 1})\n"
    ))
    code, output = run_validator(schema_file, code_file)
    assert code == 1, output
    assert "userId" in output


def test_bom_openapi_json_known_path(tmp_path):
    schema_file = write_bom(tmp_path / "openapi.json", json.dumps(OPENAPI))
    code_file = tmp_path / "client.ts"
    code_file.write_text('fetch("/users");\n', encoding="utf-8")
    code, output = run_validator(schema_file, code_file)
    assert code == 0, output


def test_bom_openapi_json_unknown_path(tmp_path):
    schema_file = write_bom(tmp_path / "openapi.json", json.dumps(OPENAPI))
    code_file = tmp_path / "client.ts"
    code_file.write_text('fetch("/nonexistent");\n', encoding="utf-8")
    code, output = run_validator(schema_file, code_file)
    assert code == 1, output
    assert "/nonexistent" in output
