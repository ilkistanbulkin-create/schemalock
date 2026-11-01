"""find_schema tests: dependency / build directories (.venv, dist, ...) must not be searched."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".schemalock"))

from schema_parser import SchemaError, find_schema  # noqa: E402

PRISMA = "model User {\n  id Int @id\n}\n"


def write_schema(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "schema.prisma"
    path.write_text(PRISMA, encoding="utf-8")
    return path


def test_root_schema_wins_over_venv(tmp_path):
    root_schema = write_schema(tmp_path)
    write_schema(tmp_path / ".venv" / "lib" / "pkg")
    assert os.path.samefile(find_schema(str(tmp_path)), root_schema)


@pytest.mark.parametrize("skipped", [".venv", "dist"])
def test_schema_only_in_skipped_dir_is_not_found(tmp_path, skipped):
    write_schema(tmp_path / skipped / "prisma")
    with pytest.raises(SchemaError):
        find_schema(str(tmp_path))


def test_schema_in_normal_subdir_is_found(tmp_path):
    schema = write_schema(tmp_path / "prisma")
    write_schema(tmp_path / "dist" / "prisma")
    assert os.path.samefile(find_schema(str(tmp_path)), schema)
