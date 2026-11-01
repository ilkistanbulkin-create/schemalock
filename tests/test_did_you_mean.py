"""Unknown column errors suggest the closest column ("Did you mean ...?") when one is close enough."""
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


def test_suggests_id_for_userId(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 "await prisma.user.findMany({ where: { userId: 1 } });\n")
    assert code == 1, output
    assert "Available columns: id, email, role" in output
    assert "Did you mean 'id'?" in output


def test_suggests_email_for_typo(tmp_path):
    code, output = run_validator(tmp_path, "app.py",
                                 'prisma.user.find_many(where={"emial": "a@b.c"})\n')
    assert code == 1, output
    assert "Available columns: id, email, role" in output
    assert "Did you mean 'email'?" in output


def test_case_is_ignored(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 'await prisma.user.findMany({ where: { EMIAL: "a@b.c" } });\n')
    assert code == 1, output
    assert "Did you mean 'email'?" in output


def test_no_suggestion_for_unrelated_name(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 "await prisma.user.findMany({ where: { xyz: 1 } });\n")
    assert code == 1, output
    assert "Did you mean" not in output


def test_message_unchanged_without_suggestion(tmp_path):
    code, output = run_validator(tmp_path, "app.ts",
                                 "await prisma.user.findMany({ where: { xyz: 1 } });\n")
    assert code == 1, output
    lines = output.splitlines()
    first = next(i for i, l in enumerate(lines) if "column 'xyz'" in l)
    assert lines[first].endswith("column 'xyz' not found in model 'User'.")
    # The column list is still the error's last line; no hint follows it.
    assert lines[first + 1:] == ["  Available columns: id, email, role"]
