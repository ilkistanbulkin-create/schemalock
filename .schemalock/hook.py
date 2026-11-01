"""Claude Code PostToolUse hook: run ast_validator.py on the file that was just edited.

Reads the hook JSON from stdin and takes tool_input.file_path.
Exit codes: 0 = nothing to do, OK, or the validator could not run (a warning is printed to
stdout as hookSpecificOutput.additionalContext so Claude sees it, Claude is not blocked),
2 = schema violations (stderr is shown to Claude).
"""
import json
import os
import subprocess
import sys

CODE_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")  # same as ast_validator
SCHEMALOCK_DIR = os.path.dirname(os.path.abspath(__file__))
VALIDATOR = os.path.join(SCHEMALOCK_DIR, "ast_validator.py")

sys.path.insert(0, SCHEMALOCK_DIR)
# Only checks that some schema exists; the validator then picks the schemas from the same
# directory with the same rule as the manual command: ast_validator.py <project_dir> <file>.
from schema_parser import SCHEMA_FILENAMES, SchemaError, find_schema  # noqa: E402


def main():
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return 0
    file_path = (data.get("tool_input") or {}).get("file_path")
    if not file_path or os.path.splitext(file_path)[1].lower() not in CODE_EXTENSIONS:
        return 0

    cwd = data.get("cwd") or os.getcwd()
    file_path = os.path.join(cwd, file_path)  # no-op when file_path is absolute
    if not os.path.isfile(file_path):
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    inside = os.path.normcase(os.path.abspath(file_path)).startswith(
        os.path.normcase(os.path.abspath(project_dir)) + os.sep)
    search_dir = project_dir if inside else os.path.dirname(os.path.abspath(file_path))
    try:
        find_schema(search_dir, SCHEMA_FILENAMES)
    except SchemaError:  # no schema: nothing to do
        return 0

    # Pass the directory, not one file: the validator loads one Prisma and one OpenAPI schema.
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, VALIDATOR, search_dir, file_path],
                            capture_output=True, env=env)
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()
    if result.returncode == 0:
        return 0
    if result.returncode == 1:
        print("SchemaLock: code does not match the schema, please fix:", file=sys.stderr)
        print(output, file=sys.stderr)
        return 2
    # Exit code 3 (schema unreadable / tool error) or anything unexpected: don't block, but warn
    # Claude. stderr is not shown to Claude on exit 0, so use the JSON additionalContext instead.
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"SchemaLock: validation skipped, reason: {output}",
        }
    }))  # ASCII-escaped JSON: safe regardless of the console encoding
    return 0


if __name__ == "__main__":
    sys.exit(main())
