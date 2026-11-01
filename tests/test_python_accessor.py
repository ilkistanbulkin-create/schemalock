"""prisma-client-py model accessors: the all-lowercase model name (UserProfile -> userprofile)."""
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

model UserProfile {
  id     Int    @id @default(autoincrement())
  bio    String
  userId Int
}
"""


def run_validator(tmp_path, code, filename="app.py"):
    schema_file = tmp_path / "schema.prisma"
    schema_file.write_text(SCHEMA, encoding="utf-8")
    code_file = tmp_path / filename
    code_file.write_text(code, encoding="utf-8")
    result = subprocess.run([sys.executable, VALIDATOR, str(schema_file), str(code_file)],
                            capture_output=True, env=ENV)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def test_lowercase_multiword_model_accepted(tmp_path):
    code = ("from prisma import Prisma\n"
            "client = Prisma()\n"
            "client.userprofile.find_many(where={'bio': 'x'})\n")
    rc, out = run_validator(tmp_path, code)
    assert rc == 0, out
    assert "OK" in out


def test_lowercase_accessor_still_checks_columns(tmp_path):
    code = ("from prisma import Prisma\n"
            "client = Prisma()\n"
            "client.userprofile.find_many(where={'nope': 'x'})\n")
    rc, out = run_validator(tmp_path, code)
    assert rc == 1, out
    assert "nope" in out


def test_unknown_model_still_rejected(tmp_path):
    code = ("from prisma import Prisma\n"
            "client = Prisma()\n"
            "client.nonexistent.find_many(where={'id': 1})\n")
    rc, out = run_validator(tmp_path, code)
    assert rc == 1, out
    assert "nonexistent" in out


def test_single_word_model_unchanged(tmp_path):
    code = ("from prisma import Prisma\n"
            "client = Prisma()\n"
            "client.user.find_many(where={'email': 'a@b.c'})\n"
            "client.User.find_many(where={'email': 'a@b.c'})\n")
    rc, out = run_validator(tmp_path, code)
    assert rc == 0, out


def test_existing_python_accessors_kept(tmp_path):
    code = ("from prisma import Prisma\n"
            "client = Prisma()\n"
            "client.userProfile.find_many(where={'bio': 'x'})\n"
            "client.UserProfile.find_many(where={'bio': 'x'})\n")
    rc, out = run_validator(tmp_path, code)
    assert rc == 0, out


def test_typescript_lowercase_accessor_unchanged(tmp_path):
    code = "await prisma.userprofile.findMany({ where: { bio: 'x' } })\n"
    rc, out = run_validator(tmp_path, code, filename="app.ts")
    assert rc == 1, out
    assert "userprofile" in out
