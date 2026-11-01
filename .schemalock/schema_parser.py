"""Extract a JSON description of a project's schema.

Supports:
  - schema.prisma (default), or every .prisma file in a prisma/schema/ directory (Prisma's
    multi-file schema) read as one schema: model (and view) names, column names and types, and enum
    blocks with their values (columns whose type is an enum get "enum": true).
  - openapi.yaml / openapi.yml / openapi.json (--openapi): endpoint paths and
    their methods, the base paths of servers[].url, plus the field names and
    types of components/schemas.

Usage: python schema_parser.py [--openapi] <project_dir>
"""
import json
import os
import re
import sys
from urllib.parse import urlsplit

PRISMA_FILENAME = "schema.prisma"
OPENAPI_FILENAMES = ("openapi.yaml", "openapi.yml", "openapi.json")
SCHEMA_FILENAMES = (PRISMA_FILENAME,) + OPENAPI_FILENAMES
SKIP_DIRS = {".venv", "venv", "node_modules", "dist", "build", ".git", "__pycache__", ".next"}
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

MODEL_RE = re.compile(r"^\s*(?:model|view)\s+(\w+)\s*\{\s*$")  # views are read like models
FIELD_RE = re.compile(r"^\s*(\w+)\s+(\w+)(\[\])?(\?)?(.*)$")
ENUM_RE = re.compile(r"^\s*enum\s+(\w+)\s*\{(.*)$")
ATTRIBUTE_RE = re.compile(r"@@?\w+(?:\.\w+)?(?:\((?:[^()]|\([^()]*\))*\))?")
COMPOUND_RE = re.compile(r"^@@(id|unique)\s*\(\s*(?:fields\s*:\s*)?\[([^\]]*)\]")
COMPOUND_NAME_RE = re.compile(r"\bname\s*:\s*\"([^\"]+)\"")


def _compound_keys(attr):
    """Where-input names of an @@id / @@unique attribute: fields joined by "_", plus name: "..." if given."""
    m = COMPOUND_RE.match(attr)
    if not m:
        return []
    fields = re.findall(r"\w+", re.sub(r"\([^()]*\)", "", m.group(2)))  # drop a(sort: Desc) arguments
    names = ["_".join(fields)] if fields else []
    custom = COMPOUND_NAME_RE.search(attr[m.end():])
    if custom:
        names.append(custom.group(1))
    return names


def _enum_values(text):
    """Enum value names in a line of an enum body, ignoring @map / @@map attributes."""
    return re.findall(r"\w+", ATTRIBUTE_RE.sub(" ", text))


class SchemaError(Exception):
    pass


def _is_prisma_schema_dir(root, files):
    """A prisma/schema/ directory holding .prisma files (multi-file Prisma schema)."""
    parent, name = os.path.split(os.path.abspath(root))
    return (name == "schema" and os.path.basename(parent) == "prisma"
            and any(f.endswith(".prisma") for f in files))


def _walk_schemas(project_dir, filenames):
    """Yield schema paths in search order, at most one per directory (earlier names win)."""
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if PRISMA_FILENAME in filenames and _is_prisma_schema_dir(root, files):
            yield root
            continue
        for filename in filenames:
            if filename in files:
                yield os.path.join(root, filename)
                break


def _nearest(candidates, near):
    """The candidate under the closest ancestor directory of near; None if only the walk can decide."""
    directory = os.path.normcase(os.path.dirname(os.path.abspath(near)))
    while True:
        for candidate in candidates:
            path = os.path.normcase(os.path.abspath(candidate))
            if path == directory or path.startswith(directory.rstrip(os.sep) + os.sep):
                return candidate
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def find_schema(project_dir, filenames=PRISMA_FILENAME, near=None):
    """Return the first schema file found; earlier names win within a directory.

    When schema.prisma is searched for, a prisma/schema/ directory with .prisma files counts as
    one schema and its directory path is returned (parse_prisma reads all of its files).
    With near (the edited file) and several schemas, the one found by climbing up from near's
    directory wins: the first ancestor holding any schema decides, then search order.
    """
    if isinstance(filenames, str):
        filenames = (filenames,)
    if not os.path.isdir(project_dir):
        raise SchemaError(f"Project directory not found: {project_dir}")
    walk = _walk_schemas(project_dir, filenames)
    if near is None:
        first = next(walk, None)
        if first is not None:
            return first
    else:
        candidates = list(walk)
        if candidates:
            return (_nearest(candidates, near) if len(candidates) > 1 else None) or candidates[0]
    raise SchemaError(f"No {' / '.join(filenames)} found in: {project_dir}")


def find_schemas(project_dir, near=None):
    """At most one schema per kind: {"prisma": path or None, "openapi": path or None}.

    Within a kind the first file found wins, or the one nearest to near (same rule as find_schema).
    """
    found = {}
    for kind, filenames in (("prisma", (PRISMA_FILENAME,)), ("openapi", OPENAPI_FILENAMES)):
        try:
            found[kind] = find_schema(project_dir, filenames, near)
        except SchemaError:
            found[kind] = None
    if not any(found.values()):
        find_schema(project_dir, SCHEMA_FILENAMES)  # raises the usual "not found" / "no directory" error
    return found


def parse_prisma(path):
    """Parse a schema.prisma file, or a directory whose .prisma files form one schema."""
    if os.path.isdir(path):
        files = sorted(os.path.join(path, f) for f in os.listdir(path) if f.endswith(".prisma"))
    else:
        files = [path]
    models = []
    enums = {}
    for file in files:
        _parse_prisma_file(file, models, enums)
    if not models:
        raise SchemaError(f"{path}: no models found")
    for model in models:
        for column in model["columns"]:
            column["enum"] = column["type"] in enums
    return {"source": "prisma", "file": path, "models": models, "enums": enums}


def _parse_prisma_file(path, models, enums):
    """Append the models and enums of one .prisma file to models / enums."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            lines = f.read().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise SchemaError(f"Cannot read {path}: {e}")

    current = None
    current_enum = None
    attr = None  # block-level attribute spanning several lines, e.g. @@id([\n a,\n b\n])
    for lineno, raw in enumerate(lines, 1):
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        if attr is not None:
            attr += " " + line
            if attr.count("(") <= attr.count(")"):
                current["compound_keys"].extend(_compound_keys(attr))
                attr = None
            continue
        if current_enum is not None:
            body, closed = line.split("}", 1)[0], "}" in line
            enums[current_enum].extend(_enum_values(body))
            if closed:
                current_enum = None
            continue
        if current is None:
            e = ENUM_RE.match(line)
            if e:
                body = e.group(2)
                enums[e.group(1)] = _enum_values(body.split("}", 1)[0])
                if "}" not in body:  # multi-line block; enum Role { USER ADMIN } is one line
                    current_enum = e.group(1)
                continue
            m = MODEL_RE.match(line)
            if m:
                current = {"name": m.group(1), "columns": [], "compound_keys": []}
            elif line.startswith("model") or re.match(r"view\b", line):
                raise SchemaError(f"{path}:{lineno}: malformed model declaration: {raw.strip()}")
            continue
        if line == "}":
            models.append(current)
            current = None
            continue
        if line.startswith("@@"):  # block-level attribute, e.g. @@index
            if line.count("(") > line.count(")"):
                attr = line
            else:
                current["compound_keys"].extend(_compound_keys(line))
            continue
        f = FIELD_RE.match(line)
        if not f:
            raise SchemaError(f"{path}:{lineno}: cannot parse field in model '{current['name']}': {raw.strip()}")
        current["columns"].append({
            "name": f.group(1),
            "type": f.group(2),
            "list": bool(f.group(3)),
            "optional": bool(f.group(4)),
            "attributes": re.findall(r"@\w+(?:\.\w+)?(?:\((?:[^()]|\([^()]*\))*\))?", f.group(5)),
        })

    if attr is not None:
        raise SchemaError(f"{path}: unterminated block attribute in model '{current['name']}': {attr}")
    if current is not None:
        raise SchemaError(f"{path}: model '{current['name']}' is missing a closing '}}'")
    if current_enum is not None:
        raise SchemaError(f"{path}: enum '{current_enum}' is missing a closing '}}'")


def _openapi_type(prop):
    """Return (type, list) for an OpenAPI property schema."""
    if not isinstance(prop, dict):
        return "unknown", False
    if "$ref" in prop:
        return str(prop["$ref"]).rsplit("/", 1)[-1], False
    if prop.get("type") == "array":
        item_type, _ = _openapi_type(prop.get("items", {}))
        return item_type, True
    return str(prop.get("type", "object")), False


def _load_openapi(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise SchemaError(f"Cannot read {path}: {e}")
    if path.lower().endswith(".json"):
        try:
            return json.loads(text)
        except ValueError as e:
            raise SchemaError(f"{path}: invalid JSON: {e}")
    try:
        import yaml
    except ImportError:
        raise SchemaError("PyYAML is not installed")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise SchemaError(f"{path}: invalid YAML: {e}")


def parse_openapi(path):
    doc = _load_openapi(path)

    if not isinstance(doc, dict):
        raise SchemaError(f"{path}: expected a YAML mapping at the top level")
    if "openapi" not in doc and "swagger" not in doc:
        raise SchemaError(f"{path}: missing 'openapi' version field; not an OpenAPI document")

    paths = doc.get("paths") or {}
    if not isinstance(paths, dict):
        raise SchemaError(f"{path}: 'paths' must be a mapping")
    endpoints = []
    for route, ops in paths.items():
        if not isinstance(ops, dict):
            raise SchemaError(f"{path}: path '{route}' must be a mapping of HTTP methods")
        methods = [m.upper() for m in ops if str(m).lower() in HTTP_METHODS]
        endpoints.append({"path": route, "methods": methods})

    components = doc.get("components") or {}
    if not isinstance(components, dict):
        raise SchemaError(f"{path}: 'components' must be a mapping")
    schemas = components.get("schemas") or {}
    if not isinstance(schemas, dict):
        raise SchemaError(f"{path}: 'components/schemas' must be a mapping")
    models = []
    for name, schema in schemas.items():
        if not isinstance(schema, dict):
            raise SchemaError(f"{path}: schema '{name}' must be a mapping")
        required = set(schema.get("required") or [])
        columns = []
        for field, prop in (schema.get("properties") or {}).items():
            ftype, is_list = _openapi_type(prop)
            columns.append({
                "name": field,
                "type": ftype,
                "list": is_list,
                "optional": field not in required,
            })
        models.append({"name": name, "columns": columns})

    if not endpoints and not models:
        raise SchemaError(f"{path}: no paths or components/schemas found")
    return {"source": "openapi", "file": path, "endpoints": endpoints, "models": models,
            "base_paths": _server_base_paths(doc.get("servers"))}


def _server_base_paths(servers):
    """Path prefixes of servers[].url: "/api/v1" and "https://host/api/v1" both give "/api/v1".

    Root ("/"), templated ("{basePath}") and malformed entries are skipped.
    """
    bases = []
    for server in servers if isinstance(servers, list) else []:
        url = server.get("url") if isinstance(server, dict) else None
        if not isinstance(url, str):
            continue
        base = urlsplit(url.strip()).path.rstrip("/")
        if base.startswith("/") and "{" not in base and base not in bases:
            bases.append(base)
    return bases


def main(argv):
    args = argv[1:]
    use_openapi = "--openapi" in args
    args = [a for a in args if a != "--openapi"]
    if len(args) != 1:
        print("Usage: python schema_parser.py [--openapi] <project_dir>", file=sys.stderr)
        return 2
    try:
        if use_openapi:
            result = parse_openapi(find_schema(args[0], OPENAPI_FILENAMES))
        else:
            result = parse_prisma(find_schema(args[0]))
    except SchemaError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
