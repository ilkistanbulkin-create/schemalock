"""Example rule: forbid DROP TABLE statements (case-insensitive, any whitespace between words)."""
import re

EXTENSIONS = [".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]

DROP_TABLE = re.compile(r"DROP\s+TABLE", re.IGNORECASE)


def check(text, checker):
    for n, line in enumerate(text.splitlines(), 1):
        if DROP_TABLE.search(line):
            checker.error(n, "DROP TABLE is not allowed")
