"""Prisma compound keys: @@id / @@unique where-input names (userId_postId) are not unknown columns."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATOR = os.path.join(ROOT, ".schemalock", "ast_validator.py")

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")

ID_SCHEMA = """\
model Like {
  userId Int
  postId Int

  @@id([userId, postId])
}
"""

UNIQUE_SCHEMA = """\
model Like {
  id     Int @id @default(autoincrement())
  userId Int
  postId Int

  @@unique([userId, postId])
}
"""

MULTILINE_ID_SCHEMA = """\
model Like {
  userId Int
  postId Int

  @@id([
    userId,
    postId
  ])
}
"""

NAMED_SCHEMA = """\
model Like {
  id     Int @id @default(autoincrement())
  userId Int
  postId Int

  @@unique([userId, postId], name: "userPost")
}
"""

FIND_UNIQUE = "await prisma.like.findUnique({{ where: {{ {key}: {{ userId: 1, postId: 2 }} }} }});\n"


def run_validator(tmp_path, schema, code, filename="app.ts"):
    schema_file = tmp_path / "schema.prisma"
    schema_file.write_text(schema, encoding="utf-8")
    code_file = tmp_path / filename
    code_file.write_text(code, encoding="utf-8")
    result = subprocess.run([sys.executable, VALIDATOR, str(schema_file), str(code_file)],
                            capture_output=True, env=ENV)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def test_compound_id(tmp_path):
    code, output = run_validator(tmp_path, ID_SCHEMA, FIND_UNIQUE.format(key="userId_postId"))
    assert code == 0, output


def test_compound_unique(tmp_path):
    code, output = run_validator(tmp_path, UNIQUE_SCHEMA, FIND_UNIQUE.format(key="userId_postId"))
    assert code == 0, output


def test_unknown_compound_name(tmp_path):
    code, output = run_validator(tmp_path, ID_SCHEMA, FIND_UNIQUE.format(key="missingName_postId"))
    assert code == 1, output
    assert "missingName_postId" in output


def test_multiline_compound_id(tmp_path):
    code, output = run_validator(tmp_path, MULTILINE_ID_SCHEMA, FIND_UNIQUE.format(key="userId_postId"))
    assert code == 0, output


def test_named_compound_unique(tmp_path):
    code, output = run_validator(tmp_path, NAMED_SCHEMA, FIND_UNIQUE.format(key="userPost"))
    assert code == 0, output


def test_python_compound_id(tmp_path):
    code, output = run_validator(tmp_path, ID_SCHEMA,
                                 'prisma.like.find_unique(where={"userId_postId": {"userId": 1, "postId": 2}})\n',
                                 filename="app.py")
    assert code == 0, output
