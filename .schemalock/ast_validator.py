"""Check that a code file only uses models and columns that exist in the schema.

  - .py files are analysed with Python's ast module:
      prisma.<model>.<op>(where={...})   (prisma-client-py)
      <Model>.prisma().<op>(where={...})
  - .ts/.js files are analysed with a small regex tokenizer (no packages):
      prisma.<model>.<op>({ ... })

Schema information comes from schema_parser.py: schema.prisma (or all .prisma files of a
multi-file prisma/schema/ directory, read as one schema), or the models in
components/schemas of openapi.yaml / openapi.yml / openapi.json.
Given a project directory, at most one schema of each kind is loaded (the first
found): Prisma calls are checked against schema.prisma (or, without one, against
the OpenAPI models) and HTTP calls against the OpenAPI schema.

With an OpenAPI schema, HTTP calls whose URL is a string literal starting with
"/" are also checked against the schema's paths and methods:
    fetch("/users/5", { method: "POST" })   axios.get("/users/5")   (.ts/.js)
    requests.get("/users/5")                                        (.py)
URLs built from variables and absolute http(s):// URLs are skipped, as are
static files (/logo.png, ...), /_next/... and /api/auth/... (framework routes).
If servers[].url has a base path (e.g. /api/v1), "/api/v1/users" and "/users"
both match the schema path /users.

With a Prisma schema, string literals given directly to an enum-typed column in
where / data (e.g. data: { role: "BOSS" }) must be one of the enum's values.
Variables and filter objects such as { in: [...] } are skipped.

Usage: python ast_validator.py <schema_file|project_dir> <code_file>
Exit codes: 0 = OK, 1 = schema violations found, 3 = schema unreadable or tool error.
"""
import ast
import os
import re
import sys

EXIT_OK, EXIT_VIOLATIONS, EXIT_TOOL_ERROR = 0, 1, 3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from schema_parser import SchemaError, find_schemas, parse_openapi, parse_prisma  # noqa: E402
    from rule_loader import load_rules  # noqa: E402
except Exception as e:  # an import-time crash would otherwise exit 1, i.e. look like a violation
    if __name__ != "__main__":
        raise
    sys.stderr.reconfigure(encoding="utf-8")
    print(f"ERROR: failed to load validator: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(EXIT_TOOL_ERROR)

JS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
OPENAPI_EXTENSIONS = (".yaml", ".yml", ".json")
RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")

# Prisma query arguments whose keys are column names, mapped to a checker name.
WHERE_ARGS = ("where", "cursor")
DATA_ARGS = ("data", "create", "update")
SELECT_ARGS = ("select", "include")
ORDER_ARGS = ("orderBy", "order")  # "order" is prisma-client-py's spelling
NAME_LIST_ARGS = ("distinct", "by")
AGGREGATE_ARGS = ("_count", "_sum", "_avg", "_min", "_max")
LOGICAL_OPS = ("AND", "OR", "NOT")
LIST_RELATION_FILTERS = ("some", "every", "none")
SINGLE_RELATION_FILTERS = ("is", "isNot")
NESTED_WHERE_OPS = ("connect", "disconnect", "delete", "set")
NESTED_DATA_OPS = ("create",)

# prisma-client-py submodules (prisma.types, prisma.models, prisma.fields, ...); not models.
PY_PRISMA_MODULES = {"types", "errors", "enums", "models", "fields", "bases", "partials"}

# Request paths that are never API endpoints of the schema, so the endpoint check skips them.
STATIC_EXTENSIONS = (".png", ".jpg", ".jpeg", ".svg", ".ico", ".css", ".js", ".map",
                     ".woff", ".woff2", ".txt", ".xml")
IGNORED_PATH_PREFIXES = ("/_next/", "/api/auth/")

# Every schema check needs one of these words in the file (prisma / Prisma() / x.prisma, fetch,
# axios, requests); without them the checks are skipped. A plain substring match, so it never misses.
QUERY_HINT_RE = re.compile(r"prisma|fetch|axios|requests", re.IGNORECASE)


def normalize_path(url):
    path = re.split(r"[?#]", url, maxsplit=1)[0]
    return path.rstrip("/") or "/"


def is_ignored_path(url):
    """Static files and framework routes (Next.js assets, NextAuth) that are not schema endpoints."""
    path = re.split(r"[?#]", url, maxsplit=1)[0]
    if path.startswith(IGNORED_PATH_PREFIXES):
        return True
    return path.rsplit("/", 1)[-1].lower().endswith(STATIC_EXTENSIONS)


def template_regex(route):
    """/users/{id} -> regex matching /users/5 (a template segment matches one path segment)."""
    parts = re.split(r"(\{[^/{}]*\})", normalize_path(route))
    pattern = "".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts if p)
    return re.compile(f"^{pattern}$")


MAX_LIST_ITEMS = 10


def short_list(items):
    """Comma-joined items for an alarm message, at most MAX_LIST_ITEMS, then ", …"."""
    items = list(items)
    text = ", ".join(items[:MAX_LIST_ITEMS]) or "none"
    return text + ", …" if len(items) > MAX_LIST_ITEMS else text


class Schema:
    def __init__(self, parsed):
        self.models = {}
        # Prisma @@id / @@unique where-input names (e.g. userId_postId), per model.
        self.compound_keys = {}
        for m in parsed["models"]:
            self.models[m["name"]] = {c["name"]: c for c in m["columns"]}
            self.compound_keys[m["name"]] = set(m.get("compound_keys", ()))
        self.enums = parsed.get("enums", {})
        # Prisma client accessors are the model name with a lowercase first letter.
        self.accessors = {}
        for name in self.models:
            self.accessors[name[0].lower() + name[1:]] = name
            self.accessors[name] = name
        # prisma-client-py accessors are the model name in all lowercase (UserProfile ->
        # userprofile); Python calls accept those as well. Existing accessors win on a clash.
        self.py_accessors = dict(self.accessors)
        for name in self.models:
            self.py_accessors.setdefault(name.lower(), name)
        # OpenAPI only; None for Prisma, which disables the endpoint check.
        self.endpoints = None
        self.base_paths = parsed.get("base_paths", [])
        if "endpoints" in parsed:
            self.endpoints = [(e["path"], template_regex(e["path"]), set(e["methods"]))
                              for e in parsed["endpoints"]]

    def endpoint_methods(self, url):
        """Methods allowed for `url` (union over matching path templates), or None if no path matches."""
        path = normalize_path(url)
        # With servers[].url base paths, try the path both as written and with the base removed.
        candidates = [path] + [path[len(base):] or "/" for base in self.base_paths
                               if path == base or path.startswith(base + "/")]
        matches = [methods for _, regex, methods in self.endpoints
                   if any(regex.match(p) for p in candidates)]
        return set().union(*matches) if matches else None

    def endpoint_list(self):
        return short_list(f"{m} {p}" for p, _, methods in self.endpoints for m in sorted(methods))

    def enum_values(self, model, column):
        """(enum name, values) if `column` of `model` is enum-typed, else (None, None)."""
        col = self.models[model].get(column)
        if col and col.get("enum") and col["type"] in self.enums:
            return col["type"], self.enums[col["type"]]
        return None, None

    def relation_target(self, model, column):
        col = self.models[model].get(column)
        if col and col["type"] in self.models:
            return col["type"], col["list"]
        return None, False


# Values are normalised into a tiny tree shared by the JS and Python front-ends:
#   ("obj", [(key, line, value), ...]) | ("arr", [value, ...]) | ("str", s, line) | ("other",)
OTHER = ("other",)


class Checker:
    def __init__(self, schema, filename, api=None):
        self.schema = schema  # models / columns / enums, for Prisma calls
        self.api = api if api is not None else schema  # endpoints, for HTTP calls
        self.filename = filename
        self.errors = []

    def error(self, line, message):
        self.errors.append((line, message))

    def unknown_model(self, line, name):
        known = short_list(sorted(self.schema.models))
        self.error(line, f"'{name}' model not found in schema.\n  Available models: {known}")

    def column(self, model, name, line):
        """Report and return False if `name` is not a column of `model`."""
        if name in self.schema.models[model]:
            return True
        known = short_list(self.schema.models[model])
        self.error(line, f"column '{name}' not found in model '{model}'.\n  Available columns: {known}")
        return False

    def enum_value(self, model, column, value):
        """Check a string literal assigned to an enum-typed column; other values are skipped."""
        if value[0] != "str":
            return
        enum, values = self.schema.enum_values(model, column)
        if enum is None or value[1] in values:
            return
        self.error(value[2], f"'{value[1]}' is not a valid value for '{model}.{column}' ({enum}).\n"
                             f"  Valid values: {short_list(values)}")

    def endpoint(self, method, url, line):
        """Check a literal request URL; only relative paths ("/...") are checked."""
        if not url.startswith("/") or url.startswith("//") or is_ignored_path(url):
            return
        method = method.upper()
        allowed = self.api.endpoint_methods(url)
        if allowed is None:
            self.error(line, f"'{url}' path not found in schema.\n  Available endpoints: {self.api.endpoint_list()}")
        elif method != ANY_METHOD and method not in allowed:
            self.error(line, f"'{url}' path has no {method} method.\n"
                             f"  Methods for this path: {short_list(sorted(allowed))}")

    def args(self, model, value, op=None):
        if value[0] != "obj":
            return
        for key, line, val in value[1]:
            if key in WHERE_ARGS:
                self.where(model, val)
            elif key in DATA_ARGS:
                self.data(model, val)
            elif key in SELECT_ARGS:
                self.select(model, val, allowed=("_all",) if op == "count" else ())
            elif key in ORDER_ARGS:
                for item in val[1] if val[0] == "arr" else [val]:
                    self.keys(model, item)
            elif key in NAME_LIST_ARGS:
                for item in val[1] if val[0] == "arr" else [val]:
                    if item[0] == "str":
                        self.column(model, item[1], item[2])
            elif key in AGGREGATE_ARGS:
                self.keys(model, val, allowed=("_all",))

    def keys(self, model, value, allowed=()):
        if value[0] != "obj":
            return
        for key, line, _ in value[1]:
            if key is not None and key not in allowed:
                self.column(model, key, line)

    def where(self, model, value):
        if value[0] == "arr":
            for item in value[1]:
                self.where(model, item)
            return
        if value[0] != "obj":
            return
        for key, line, val in value[1]:
            if key is None:
                continue
            if key in LOGICAL_OPS:
                self.where(model, val)
                continue
            if key in self.schema.compound_keys[model]:  # { userId_postId: {...} }; fields not checked
                continue
            if not self.column(model, key, line):
                continue
            self.enum_value(model, key, val)
            target, is_list = self.schema.relation_target(model, key)
            if not target or val[0] != "obj":
                continue
            filters = LIST_RELATION_FILTERS if is_list else SINGLE_RELATION_FILTERS
            if any(k in filters for k, _, _ in val[1]):
                for k, _, v in val[1]:
                    if k in filters:
                        self.where(target, v)
            elif not is_list:
                self.where(target, val)

    def data(self, model, value):
        if value[0] == "arr":
            for item in value[1]:
                self.data(model, item)
            return
        if value[0] != "obj":
            return
        for key, line, val in value[1]:
            if key is None or not self.column(model, key, line):
                continue
            self.enum_value(model, key, val)
            target, _ = self.schema.relation_target(model, key)
            if not target or val[0] != "obj":
                continue
            for k, _, v in val[1]:
                if k in NESTED_WHERE_OPS:
                    self.where(target, v)
                elif k in NESTED_DATA_OPS:
                    self.data(target, v)

    def select(self, model, value, allowed=()):
        if value[0] != "obj":
            return
        for key, line, val in value[1]:
            if key is None or key == "_count" or key in allowed or not self.column(model, key, line):
                continue
            target, _ = self.schema.relation_target(model, key)
            if target:
                self.args(target, val)


# ---------------------------------------------------------------- TS / JS

TOKEN_RE = re.compile(r"""
     (?P<ws>\s+)
    |(?P<comment>//[^\n]*|/\*.*?\*/)
    |(?P<str>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')
    |(?P<tpl>`(?:\\.|[^`\\])*`)
    |(?P<id>[A-Za-z_$][\w$]*)
    |(?P<num>\d[\w.]*)
    |(?P<op>\?\.|\.\.\.|=>|[{}()\[\],:.;?])
    |(?P<other>.)
""", re.S | re.X)

OPENERS, CLOSERS = "([{", ")]}"


def tokenize_js(text):
    tokens = []
    line = 1
    for m in TOKEN_RE.finditer(text):
        kind, value = m.lastgroup, m.group()
        if kind not in ("ws", "comment"):
            tokens.append((kind, value, line))
        line += value.count("\n")
    return tokens


class JsParser:
    def __init__(self, tokens):
        self.t = tokens

    def val(self, i):
        return self.t[i][1] if i < len(self.t) else None

    def skip_expr(self, i):
        """Skip to the ',' or closing bracket that ends the current expression."""
        depth = 0
        while i < len(self.t):
            kind, v, _ = self.t[i]
            if kind == "op":
                if v in OPENERS:
                    depth += 1
                elif v in CLOSERS:
                    if depth == 0:
                        return i
                    depth -= 1
                elif v == "," and depth == 0:
                    return i
            i += 1
        return i

    def value(self, i):
        """Parse a value starting at i; return (tree, index after value)."""
        v = self.val(i)
        if v == "{":
            return self.obj(i)
        if v == "[":
            return self.arr(i)
        kind = self.t[i][0] if i < len(self.t) else None
        if kind == "str" and self.val(i + 1) in (",", "}", "]", ")"):
            return ("str", self.t[i][1][1:-1], self.t[i][2]), i + 1
        return OTHER, self.skip_expr(i)

    def obj(self, i):
        entries = []
        i += 1
        while i < len(self.t) and self.val(i) != "}":
            kind, v, line = self.t[i]
            if v == "...":
                i = self.skip_expr(i + 1)
            else:
                key = None
                if kind in ("id", "num"):
                    key = v
                elif kind == "str":
                    key = v[1:-1]
                elif v == "[":  # computed key
                    i = self.skip_expr(i + 1)
                i += 1
                if self.val(i) == ":":
                    value, i = self.value(i + 1)
                    entries.append((key, line, value))
                elif self.val(i) in (",", "}"):  # shorthand { email }
                    entries.append((key, line, OTHER))
                else:  # method or something unexpected
                    i = self.skip_expr(i)
            if self.val(i) == ",":
                i += 1
            elif self.val(i) != "}":
                i = self.skip_expr(i)
                if self.val(i) in (")", "]"):
                    i += 1
        return ("obj", entries), i + 1

    def arr(self, i):
        items = []
        i += 1
        while i < len(self.t) and self.val(i) != "]":
            if self.val(i) == ",":
                i += 1
                continue
            item, i = self.value(i)
            items.append(item)
            if self.val(i) not in (",", "]"):
                i = self.skip_expr(i)
                if self.val(i) in (")", "}"):
                    i += 1
        return ("arr", items), i + 1


def js_accessor(tokens, i):
    """Model accessor after `prisma` at token i: `.user`, `?.user`, `['user']`, `?.["user"]`.

    Returns (name, line, index after the accessor) or None.
    """
    def tok(j):
        return tokens[j] if j < len(tokens) else (None, None, None)

    j = i + 1
    if tok(j)[1] == "?." and tok(j + 1)[1] == "[":
        j += 1
    if tok(j)[1] in (".", "?.") and tok(j + 1)[0] == "id":
        return tok(j + 1)[1], tok(j + 1)[2], j + 2
    if tok(j)[1] == "[" and tok(j + 1)[0] == "str" and tok(j + 2)[1] == "]":
        return tok(j + 1)[1][1:-1], tok(j + 1)[2], j + 3
    return None


def check_js(text, checker):
    tokens = tokenize_js(text)
    parser = JsParser(tokens)
    for i in range(len(tokens)):
        if not (tokens[i][0] == "id" and tokens[i][1] == "prisma"):
            continue
        found = js_accessor(tokens, i)
        if found is None:
            continue
        accessor, line, j = found
        # prisma.<model>.<op>(
        if not (parser.val(j) in (".", "?.") and j + 1 < len(tokens) and tokens[j + 1][0] == "id"
                and parser.val(j + 2) == "("):
            continue
        if i > 0 and tokens[i - 1][1] in (".", "?.") and tokens[i - 2][1] != "this":
            continue  # e.g. foo.prisma where foo is not `this`
        if accessor.startswith("$"):  # $transaction, $queryRaw, ...
            continue
        model = checker.schema.accessors.get(accessor)
        if model is None:
            checker.unknown_model(line, accessor)
            continue
        if parser.val(j + 3) == "{":
            tree, _ = parser.obj(j + 3)
            checker.args(model, tree, op=tokens[j + 1][1])


HTTP_CALL_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
GLOBAL_OBJECTS = ("window", "globalThis", "self")
ANY_METHOD = "*"  # method not known statically (e.g. `method: m`): only the path is checked


def js_literal(token):
    """String value of a plain string / template literal token without ${...}, else None."""
    kind, v, _ = token
    if kind == "str" or (kind == "tpl" and "${" not in v):
        return v[1:-1]
    return None


def js_option_method(parser, i):
    """`method: "..."` from an options object starting at token i; ANY_METHOD if the method
    is not known statically (`method: m`, `opts`, `{ ...opts }`), None if there is no method key."""
    if parser.val(i) != "{":
        return ANY_METHOD
    tree, end = parser.obj(i)
    depth = 0
    for j in range(i + 1, end - 1):
        kind, v, _ = parser.t[j]
        if kind != "op":
            continue
        if v in OPENERS:
            depth += 1
        elif v in CLOSERS:
            depth -= 1
        elif v == "..." and depth == 0:
            return ANY_METHOD
    for key, _, val in tree[1]:
        if key == "method":
            return val[1] if val[0] == "str" else ANY_METHOD
    return None


def check_js_http(text, checker):
    tokens = tokenize_js(text)
    parser = JsParser(tokens)
    for i, (kind, name, line) in enumerate(tokens):
        if kind != "id" or name not in ("fetch", "axios"):
            continue
        if i > 0 and tokens[i - 1][1] in (".", "?."):
            if name != "fetch" or i < 2 or tokens[i - 2][1] not in GLOBAL_OBJECTS:
                continue  # foo.fetch(...) is not the global fetch
        if i > 0 and tokens[i - 1][1] == "function":
            continue
        j, method = i + 1, None
        if name == "axios" and parser.val(j) == "." and parser.val(j + 1) in HTTP_CALL_METHODS:
            method, j = parser.val(j + 1), j + 2
        if parser.val(j) != "(" or j + 2 >= len(tokens) or parser.val(j + 2) not in (",", ")"):
            continue
        url = js_literal(tokens[j + 1])
        if url is None:
            continue  # URL built from variables
        if method is None:  # fetch(url, opts) / axios(url, config)
            method = (js_option_method(parser, j + 3) if parser.val(j + 2) == "," else None) or "GET"
        checker.endpoint(method, url, tokens[j + 1][2])


# ---------------------------------------------------------------- Python

def py_value(node):
    if isinstance(node, ast.Dict):
        entries = []
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                entries.append((k.value, k.lineno, py_value(v)))
        return ("obj", entries)
    if isinstance(node, (ast.List, ast.Tuple)):
        return ("arr", [py_value(e) for e in node.elts])
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return ("str", node.value, node.lineno)
    return OTHER


def py_call_args(call):
    """Prisma-client-py style keyword arguments as an "obj" tree."""
    entries = [(kw.arg, kw.value.lineno, py_value(kw.value)) for kw in call.keywords if kw.arg]
    if call.args and isinstance(call.args[0], ast.Dict):
        entries.extend(py_value(call.args[0])[1])
    return ("obj", entries)


def is_prisma_constructor(node):
    """Prisma() / prisma.Prisma() / the `prisma` name itself."""
    if isinstance(node, ast.Name) and node.id == "prisma":
        return True
    if isinstance(node, ast.Call):
        func = node.func
        return (isinstance(func, ast.Name) and func.id == "Prisma") or \
               (isinstance(func, ast.Attribute) and func.attr == "Prisma")
    return False


def py_client_names(tree):
    """Names bound in this file by `x = Prisma()`, `x = prisma` or `with Prisma() as x:`."""
    names = {"prisma"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and is_prisma_constructor(node.value):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if is_prisma_constructor(item.context_expr) and isinstance(item.optional_vars, ast.Name):
                    names.add(item.optional_vars.id)
    return names


def is_prisma_client(node, names):
    return (isinstance(node, ast.Name) and node.id in names) or \
           (isinstance(node, ast.Attribute) and node.attr == "prisma")


def check_python(text, checker):
    tree = ast.parse(text, filename=checker.filename)
    models = checker.schema.models
    clients = py_client_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            target = node.func.value
            # prisma.<model>.<op>(...)
            if isinstance(target, ast.Attribute) and is_prisma_client(target.value, clients):
                model = checker.schema.py_accessors.get(target.attr)
                if model is None and target.attr in PY_PRISMA_MODULES:
                    pass  # prisma.types.UserCreateInput(...), prisma.models.User(...), prisma.fields...
                elif model is None:
                    checker.unknown_model(target.lineno, target.attr)
                else:
                    checker.args(model, py_call_args(node), op=node.func.attr)
            # <Model>.prisma().<op>(...)
            elif (isinstance(target, ast.Call) and isinstance(target.func, ast.Attribute)
                  and target.func.attr == "prisma" and isinstance(target.func.value, ast.Name)
                  and target.func.value.id in models):
                checker.args(target.func.value.id, py_call_args(node), op=node.func.attr)


def py_str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def check_python_http(text, checker):
    """requests.<method>("/path") and requests.request("METHOD", "/path")."""
    tree = ast.parse(text, filename=checker.filename)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "requests"):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        attr = node.func.attr
        if attr in HTTP_CALL_METHODS:
            method = attr
            url_node = node.args[0] if node.args else kwargs.get("url")
        elif attr == "request":
            method = py_str(node.args[0] if node.args else kwargs.get("method"))
            url_node = node.args[1] if len(node.args) > 1 else kwargs.get("url")
        else:
            continue
        url = py_str(url_node)
        if method is not None and url is not None:
            checker.endpoint(method, url, url_node.lineno)


# ---------------------------------------------------------------- main

def load_schemas(schema_path, code_file=None):
    """(schema for Prisma calls, OpenAPI schema for HTTP calls or None).

    A project directory loads the first schema.prisma (or prisma/schema/ directory of .prisma
    files) and the first openapi.* found; when a kind has several, the one nearest to code_file;
    a single schema file is used for both.
    """
    if not os.path.isdir(schema_path):
        schema = load_schema(schema_path)
        return schema, schema if schema.endpoints is not None else None
    found = find_schemas(schema_path, near=code_file)
    prisma = Schema(parse_prisma(found["prisma"])) if found["prisma"] else None
    api = Schema(parse_openapi(found["openapi"])) if found["openapi"] else None
    return prisma or api, api


def load_schema(schema_path):
    """Parse a single schema file."""
    ext = os.path.splitext(schema_path)[1].lower()
    if ext == ".prisma":
        return Schema(parse_prisma(schema_path))
    if ext in OPENAPI_EXTENSIONS:
        return Schema(parse_openapi(schema_path))
    raise SchemaError(f"{schema_path}: unsupported schema file (expected .prisma, .yaml, .yml, or .json)")


def run_rules(text, checker, ext):
    """Run custom rules from RULES_DIR whose EXTENSIONS include `ext`; rules report via checker.error.

    A rule that fails to load or raises is reported as a warning on stderr and never changes the exit code.
    """
    rules, warnings = load_rules(RULES_DIR)
    for warning in warnings:
        print(f"WARNING: could not load rule: {warning}", file=sys.stderr)
    for rule in rules:
        if ext not in rule.EXTENSIONS:
            continue
        try:
            rule.check(text, checker)
        except (Exception, SystemExit) as e:
            name = os.path.basename(getattr(rule, "__file__", "") or rule.__name__)
            print(f"WARNING: rule error: {name}: {type(e).__name__}: {e}", file=sys.stderr)


def main(argv):
    for stream in (sys.stdout, sys.stderr):  # Non-ASCII messages on Windows consoles
        stream.reconfigure(encoding="utf-8")
    if len(argv) != 3:
        print("Usage: python ast_validator.py <schema_file|project_dir> <code_file>", file=sys.stderr)
        return EXIT_TOOL_ERROR
    schema_path, code_file = argv[1], argv[2]
    ext = os.path.splitext(code_file)[1].lower()
    if ext != ".py" and ext not in JS_EXTENSIONS:
        print(f"ERROR: {code_file}: unsupported file type '{ext}' (expected .py, .ts, or .js)", file=sys.stderr)
        return EXIT_TOOL_ERROR
    try:
        schema, api = load_schemas(schema_path, code_file)
    except SchemaError as e:
        print(f"ERROR: could not read schema: {e}", file=sys.stderr)
        return EXIT_TOOL_ERROR
    try:
        with open(code_file, encoding="utf-8-sig") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"ERROR: could not read {code_file}: {e}", file=sys.stderr)
        return EXIT_TOOL_ERROR

    checker = Checker(schema, code_file, api)
    has_queries = QUERY_HINT_RE.search(text) is not None  # fast exit: skip the schema checks
    if ext == ".py":
        try:
            if has_queries:
                check_python(text, checker)
                if api is not None:
                    check_python_http(text, checker)
            else:  # still parse, so syntax errors are reported as before
                ast.parse(text, filename=code_file)
        except SyntaxError as e:
            print(f"ERROR: {code_file}:{e.lineno}: Python syntax error: {e.msg}", file=sys.stderr)
            return EXIT_TOOL_ERROR
    elif has_queries:
        check_js(text, checker)
        if api is not None:
            check_js_http(text, checker)

    run_rules(text, checker, ext)  # custom rules run on every file

    if checker.errors:
        for line, message in sorted(set(checker.errors)):
            print(f"ERROR: {code_file}:{line}: {message}")
        return EXIT_VIOLATIONS
    print("OK")
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as e:  # an unexpected crash would otherwise exit 1, i.e. look like a violation
        print(f"ERROR: validator error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(EXIT_TOOL_ERROR)
