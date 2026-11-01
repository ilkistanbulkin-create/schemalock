"""rule_loader.load_rules: loads valid rules, skips broken/incomplete ones without raising."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".schemalock"))
sys.dont_write_bytecode = True

from rule_loader import load_rules  # noqa: E402

VALID_RULE = """\
EXTENSIONS = [".py"]

def check(text, checker):
    return []
"""


def test_valid_rule_loaded(tmp_path):
    (tmp_path / "good.py").write_text(VALID_RULE, encoding="utf-8")
    rules, warnings = load_rules(str(tmp_path))
    assert len(rules) == 1
    assert rules[0].EXTENSIONS == [".py"]
    assert callable(rules[0].check)
    assert warnings == []


def test_syntax_error_rule_skipped_with_warning(tmp_path):
    (tmp_path / "good.py").write_text(VALID_RULE, encoding="utf-8")
    (tmp_path / "broken.py").write_text("def check(text, checker:\n", encoding="utf-8")
    rules, warnings = load_rules(str(tmp_path))
    assert len(rules) == 1
    assert len(warnings) == 1
    assert "broken.py" in warnings[0]


def test_rule_without_check_skipped(tmp_path):
    (tmp_path / "nocheck.py").write_text('EXTENSIONS = [".py"]\n', encoding="utf-8")
    rules, warnings = load_rules(str(tmp_path))
    assert rules == []
    assert any("nocheck.py" in w for w in warnings)


def test_underscore_files_ignored(tmp_path):
    (tmp_path / "_helper.py").write_text(VALID_RULE, encoding="utf-8")
    rules, warnings = load_rules(str(tmp_path))
    assert rules == []
    assert warnings == []


def test_missing_dir_returns_empty(tmp_path):
    rules, warnings = load_rules(str(tmp_path / "does_not_exist"))
    assert rules == []
    assert warnings == []
