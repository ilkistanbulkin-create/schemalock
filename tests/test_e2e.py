"""End-to-end tests: run ast_validator.py and hook.py as subprocesses on the sample files."""
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMALOCK = os.path.join(ROOT, ".schemalock")
VALIDATOR = os.path.join(SCHEMALOCK, "ast_validator.py")
HOOK = os.path.join(SCHEMALOCK, "hook.py")
SAMPLE = os.path.join(ROOT, "tests", "ClaudeCodeSample")
GOOD = os.path.join(SAMPLE, "good.ts")
BAD = os.path.join(SAMPLE, "bad.ts")

ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", CLAUDE_PROJECT_DIR=ROOT)


def run_validator(code_file, schema_dir=SAMPLE):
    result = subprocess.run([sys.executable, VALIDATOR, schema_dir, code_file],
                            capture_output=True, env=ENV)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def run_hook(code_file):
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "cwd": ROOT,
        "tool_input": {"file_path": code_file},
    }
    result = subprocess.run([sys.executable, HOOK], input=json.dumps(payload).encode("utf-8"),
                            capture_output=True, env=ENV)
    return result.returncode, (result.stdout + result.stderr).decode("utf-8", errors="replace")


def test_good_passes_validator():
    code, output = run_validator(GOOD)
    assert code == 0, output


def test_bad_fails_validator_and_mentions_userid():
    code, output = run_validator(BAD)
    assert code == 1, output
    assert "userId" in output


def test_hook_blocks_bad():
    code, output = run_hook(BAD)
    assert code == 2, output
    assert "userId" in output


def test_fix_simulation(tmp_path):
    # Work on copies so the real sample directory is never written to.
    for name in ("schema.prisma", "openapi.yaml", "bad.ts"):
        shutil.copy2(os.path.join(SAMPLE, name), tmp_path / name)
    bad = str(tmp_path / "bad.ts")
    fixed_path = str(tmp_path / "fixed.ts")

    with open(bad, encoding="utf-8") as f:
        original = f.read()
    # 'userId' is not a User column; the schema's primary key is 'id'.
    fixed = re.sub(r"\buserId(\s*:)", r"id\1", original)
    assert fixed != original
    with open(fixed_path, "w", encoding="utf-8") as f:
        f.write(fixed)

    code, output = run_validator(fixed_path, str(tmp_path))
    assert code == 0, output
    code, output = run_hook(fixed_path)
    assert code == 0, output

    with open(bad, encoding="utf-8") as f:
        assert f.read() == original  # bad.ts itself is untouched
    with open(BAD, encoding="utf-8") as f:
        assert f.read() == original  # the real bad.ts is untouched too
