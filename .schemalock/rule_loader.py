"""Load custom rule modules from a directory.

Each rule is a .py file defining:
  EXTENSIONS  - list/tuple of file extensions the rule applies to (e.g. [".py", ".ts"])
  check(text, checker) - callable run against the file text

Files whose name starts with "_" are skipped. Loading never raises:
load_rules returns (rules, warnings).
"""
import importlib.util
import os


def load_rules(rules_dir):
    rules = []
    warnings = []
    try:
        if not rules_dir or not os.path.isdir(rules_dir):
            return rules, warnings
        names = sorted(os.listdir(rules_dir))
    except Exception as e:
        warnings.append(f"rules dir unreadable: {rules_dir}: {e}")
        return rules, warnings

    for name in names:
        if not name.endswith(".py") or name.startswith("_"):
            continue
        path = os.path.join(rules_dir, name)
        if not os.path.isfile(path):
            continue
        mod_name = "schemalock_rule_" + name[:-3]
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                warnings.append(f"{name}: could not create import spec, skipped")
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except (Exception, SystemExit) as e:
            warnings.append(f"{name}: failed to load ({type(e).__name__}: {e}), skipped")
            continue

        exts = getattr(module, "EXTENSIONS", None)
        check = getattr(module, "check", None)
        if not isinstance(exts, (list, tuple)):
            warnings.append(f"{name}: missing or invalid EXTENSIONS, skipped")
            continue
        if not callable(check):
            warnings.append(f"{name}: missing check(text, checker), skipped")
            continue
        rules.append(module)

    return rules, warnings
