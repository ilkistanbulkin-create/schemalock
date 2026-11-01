"""Example rule: forbid creating tables named temp_* (case-insensitive)."""
import re

EXTENSIONS = [".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]

PATTERN = re.compile(r"CREATE\s+TABLE\s+temp_", re.IGNORECASE)


def check(text, checker):
    for n, line in enumerate(text.splitlines(), 1):
        if PATTERN.search(line):
            checker.error(n, "temp_ tables are not allowed")
