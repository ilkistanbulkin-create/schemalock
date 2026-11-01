---
name: schemalock
description: When writing or changing .py/.ts/.tsx/.js/.jsx/.mjs/.cjs code in a project with a Prisma/OpenAPI schema, use ast_validator.py to verify the code matches the schema's models, columns, enum values and (for OpenAPI) endpoints.
---

# SchemaLock

If the project has a schema (`schema.prisma`, `prisma/schema.prisma`, `openapi.yaml`, `openapi.yml` or `openapi.json`) and you wrote or changed a file with one of these extensions, validate it:

`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`

## Command (works from any directory)

The validator is `.schemalock/ast_validator.py` in the project root. Do not use relative paths; the working directory may not be the project root. The **absolute path of the skill directory** shown when this skill loads has the form `<project>/.claude/skills/schemalock`; the project root is three levels above it. Build the command with absolute paths:

```
python "<project_root>/.schemalock/ast_validator.py" "<schema_file_or_folder>" "<changed_file>"
```

- If `python` is not found, use `python3` (Python 3.8+ required).
- On Windows, Git Bash is required.
- If PyYAML is missing and an `openapi.yaml`/`openapi.yml` schema is present, validation is skipped entirely (Prisma included, exit 3); suggest the user run `pip install pyyaml`.

Example (if the project root is `C:/dev/app`):

```
python "C:/dev/app/.schemalock/ast_validator.py" "C:/dev/app/prisma/schema.prisma" "C:/dev/app/src/users.ts"
```

- The first argument can be a schema file or a directory; if a directory is given, the first schema file inside it is used.
- Give all three paths as absolute paths so the command gives the same result no matter which directory it runs from.

## What is checked

- **Models and columns:** In `prisma.<model>.<operation>({ ... })` (TS/JS), `prisma.<model>.<operation>(where={...})` and `<Model>.prisma().<operation>(...)` (Python) calls: the model name, and column names inside `where`, `cursor`, `data`, `create`, `update`, `select`, `include`, `orderBy`/`order`, `distinct`, `by`, `_count`/`_sum`/`_avg`/`_min`/`_max`. `AND`/`OR`/`NOT`, relation filters (`some`/`every`/`none`, `is`/`isNot`) and nested `connect`/`disconnect`/`delete`/`set`/`create` are also followed. `@@id`/`@@unique` compound key names (e.g. `userId_postId`) are accepted. In Python, the model name in `prisma.<model>` is written all lowercase (`UserProfile` -> `prisma.userprofile`).
- **Enum check (Prisma schema only):** A string literal written directly to an enum-typed column in `where` or `data` (e.g. `data: { role: "BOSS" }`) must be one of that enum's values. Variables and filter objects like `{ in: [...] }` are skipped. The error message lists the valid values.
- **Endpoint check (OpenAPI schema only):** HTTP calls whose URL is a string literal starting with `/` are compared against the schema's `paths` and methods:
  - TS/JS: `fetch("/users/5", { method: "POST" })` (GET if no method is given), `axios.get("/users/5")`, `axios("/users", { method: "..." })`
  - Python: only the `requests.get("/users/5")` and `requests.request("POST", "/users")` forms are recognized. **Does not work in practice:** `requests` rejects relative URLs (raises `MissingSchema`), and real code writes `f"{BASE}/users"` or `"https://.../users"`; these are skipped because they are variable-based or absolute URLs. Do not trust an `OK` result for Python HTTP calls.
  - Template segments like `/users/{id}` match a single path segment. If `servers[].url` contains a base path (e.g. `/api/v1`), both `/api/v1/users` and `/users` match `/users` in the schema.
  - Skipped: URLs built from variables, static files (`/logo.png`, `.css`, `.js` etc.), `/_next/...` and `/api/auth/...`.
- **Project rules:** Every `.py` rule file in `.schemalock/rules/` also runs. Rule violations also give exit 1 and are fixed like schema violations. Files in `.schemalock/rules_examples/` do not run (copy them into `rules/` to use them). A broken rule is skipped with a stderr warning. **Security:** rules are Python code; do not add a rule you have not read.

## Exit codes and what to do

1. **Exit 0 — `OK`:** Done.
2. **Exit 1 — `ERROR:` lines:** The code does not match the schema or a project rule. Each line gives the file, line and problem (missing model/column, invalid enum value, missing path or method); valid options are listed in parentheses. Fix the code yourself to match the schema. **Do not change the schema.**
3. **Exit 3 — validation could not run:** This does not mean the code is wrong; the tool could not run. Causes: schema unreadable/broken or unsupported schema type, code file unreadable, unsupported file extension, Python syntax error, wrong number of arguments, or an unexpected validator error. Read the message; if the problem is in your code (e.g. a syntax error), fix it and rerun; otherwise report the cause to the user.
4. After fixing, rerun the validator. Repeat steps 2–4 until you see `OK`.
5. If it is not fixed after 3 attempts, stop, show the remaining errors and ask the user how to proceed.

## Hook

The PostToolUse hook (`.schemalock/hook.py`, defined in `.claude/settings.json` for `Edit|Write|MultiEdit`) runs automatically after a file with one of the 7 extensions above is edited; the edit is already written to disk. Schemas are found with `find_schemas`: it searches downward from the project root (skipping `node_modules`, `.venv`, `dist`, `build`, `.git`, `.next` etc.) for `schema.prisma`, `openapi.yaml`, `openapi.yml`, `openapi.json`. If no schema is found, it does nothing.

- Prisma and OpenAPI schemas are loaded together: Prisma calls are checked against the Prisma schema, HTTP calls against the OpenAPI schema.
- If there are several schemas of the same type (e.g. several `schema.prisma` in a monorepo), the one in the directory closest to the edited file is chosen: it walks up from the file's directory, and the first directory with a schema beneath it decides.
- A multi-file Prisma schema (multiple `.prisma` files) in the `prisma/schema/` directory is read as a single schema.

- If the validator exits 1, the hook reports the errors back to you with exit 2 (it does not block or undo the edit): fix them the same way; this counts toward the attempt limit.
- If the validator exits 3 (or an unexpected code), the hook does not report an error; it only passes the warning `SchemaLock: validation skipped, reason: ...` as additional context. If you see this warning, follow the exit 3 step above.

## KNOWN LIMITATIONS

The following are not checked; an `OK` result does not guarantee the code is correct in these cases:

- In TS, calls via aliases (`tx`, `ctx.prisma`, `db`), generic calls like `findMany<...>`, clients assigned with a type annotation, arguments coming from function parameters or other files, in Python calls via `tx` / `batch_()`, and URLs built from variables are not checked.
- In Python, keyword-style forms like `dict(role="BOSS")` are not read; SQLAlchemy-style access such as `User.nonexistent_column` is not checked.
- If a compound key is given a custom name with `name:`, the old name (`userId_postId`) is also accepted.
- `where`/`data` stored in a variable, enum values inside filter objects (`{ equals }`, `{ in }`, `{ not }`, `{ notIn }`), and nested `connectOrCreate`/`upsert`/`createMany`/`update`/`updateMany`/`deleteMany` inside relations are not checked.
- Field names inside `@@id`/`@@unique` compound keys are not validated.
- axios instances, `axios.request(...)`, config-only `axios({ url })`, and Python HTTP clients other than `requests` (e.g. `httpx`) are not checked.
- Edits made via Bash (`sed`, `>`) do not trigger the hook; old code is not rechecked when the schema changes.
- Absolute `https://...` requests written in code are not checked.
- In `fetch`, a literal method written next to a spread (`...`), like `{ ...opts, method: "GET" }`, is not checked.
- For files outside the project, the hook looks for the schema in the file's own directory (and below), not in the project root.
- A multi-file Prisma schema is only recognized in the `prisma/schema/` directory; `.prisma` files in differently named directories are not merged into one schema.
- If either the Prisma or OpenAPI schema cannot be read (is broken), validation is skipped entirely (the validator exits 3; the hook reports no error and only passes a warning with exit 0); the readable schema is not used either.
- In Python, a custom accessor name given on a model with `/// @Python(instance_name: "...")` is not recognized; correct code using that name may wrongly produce errors.
- In Python, if the Prisma client is imported from another file (no `client = Prisma()` in the same file), calls are not checked.
- In a project with an OpenAPI schema but no Prisma schema, `prisma.x.y(...)` calls are checked against the OpenAPI component schemas, which can cause false alarms. Such an `ERROR` may not be real: compare it with the actual data model before changing code, and tell the user if it looks false.
