"""Python code that must not be reported: model class attributes and prisma-client-py submodules."""
import os
import subprocess
import sys

import pytest

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


def run_validator(tmp_path, code):
    schema_file = tmp_path / "schema.prisma"
    schema_file.write_text(SCHEMA, encoding="utf-8")
    code_file = tmp_path / "app.py"
    code_file.write_text(code, encoding="utf-8")
    result = subprocess.run([sys.executable, VALIDATOR, str(schema_file), str(code_file)],
                            capture_output=True, env=ENV)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


@pytest.mark.parametrize("code", [
    "user = User.model_validate({'id': 1, 'email': 'a@b.c'})\n",
    "try:\n    pass\nexcept User.DoesNotExist:\n    pass\n",
    "fields = User._meta.get_fields()\n",
    "import prisma\n"
    "user = prisma.models.User(id=1, email='a@b.c')\n"
    "data = prisma.fields.Json({'a': 1})\n"
    "base = prisma.bases.BaseUser()\n"
    "part = prisma.partials.UserOnlyEmail(email='a@b.c')\n",
], ids=["model_validate", "DoesNotExist", "_meta", "prisma_submodules"])
def test_no_false_positive(tmp_path, code):
    code_, output = run_validator(tmp_path, code)
    assert code_ == 0, output


def test_model_prisma_valid_column(tmp_path):
    code, output = run_validator(tmp_path, "users = User.prisma().find_many(where={'email': 'a@b.c'})\n")
    assert code == 0, output


def test_model_prisma_unknown_column_still_caught(tmp_path):
    code, output = run_validator(tmp_path, 'users = User.prisma().find_many(where={"missing": 1})\n')
    assert code == 1, output
    assert "missing" in output
