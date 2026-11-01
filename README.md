# 🔒 SchemaLock — Agentic Contract Guard

### Your schema is the law. SchemaLock makes AI obey it.

AI can write a feature in seconds. It can also invent a column that doesn't exist, call an endpoint nobody defined, and quietly break your contract. You find out in production.

**SchemaLock is a contract drift guardian for AI coding assistants like Claude Code.** It reads your database schema and API contract, checks every file the AI edits, and flags the moment the code stops matching reality. The error goes straight back to Claude, Claude fixes its own mistake, and keeps going. You never had to notice.

> Tools like oasdiff compare two versions of an OpenAPI schema, and Pact tests consumers against providers. SchemaLock is the first tool that checks the code an AI writes against your schema, the moment it is written.

## See it work

Your schema has `User { id, email, role }`. Claude writes:

```ts
await prisma.user.findMany({ where: { userId: 1 } });
```

Caught instantly: `userId` is not a field of `User`. The error is sent back to Claude, which corrects it to `id`. Done.

## What it guards

**Prisma** (TypeScript, JavaScript, Python)
- Models and fields in `where`, `data`, `select`, `include`, `orderBy`, `create`, `update`, `distinct`, `by` and aggregates
- Nested filters and relations (`AND`/`OR`/`NOT`, `some`/`every`/`none`, `connect`, nested `create`)
- Enum values written as plain strings
- Single-file schemas, multi-file schemas (`prisma/schema/`) and monorepos (the nearest schema wins)

**OpenAPI**
- TypeScript/JavaScript: `fetch` and `axios` calls to fixed `/...` paths, checked for path and HTTP method. The `servers[].url` base path (for example `/api/v1`) is stripped before matching. Static files, `/_next/...` and `/api/auth/...` are skipped.
- Python: `requests` calls are checked too, but in practice this almost never triggers (see Known limits).

**When it runs:** automatically after every `Edit`, `Write` and `MultiEdit` on `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs` files. If no schema is found, it stays quiet. If the schema is broken or the file has a syntax error, it warns instead of blocking.

## Install in a minute

Copy into your project:

- `.schemalock/` (`hook.py`, `ast_validator.py`, `schema_parser.py`)
- `.claude/settings.json` (the `PostToolUse` hook). Already have one? Add the hook entry to your existing `hooks.PostToolUse` list instead of overwriting.
- `.claude/skills/schemalock/SKILL.md` (optional, teaches Claude to run the checks by hand)

Needs:
- Python 3.8 or newer on your PATH, as `python` or `python3`. The hook uses `python` if it exists, otherwise `python3`.
- `pyyaml` if you use a YAML OpenAPI spec. Without it, validation is skipped entirely, Prisma checks included.
- Git Bash on Windows (the hook command uses POSIX shell syntax).

## How it plugs into Claude Code

A hook reports, a skill teaches. The hook runs after each edit and feeds violations straight back to Claude (exit code 2). The edit itself has already been written to disk, so Claude's next move is to fix it. The skill gives Claude the context to run the same checks by hand and correct errors properly. That is the self-healing loop: mistake, report, fix, continue.

## Write your own rules

Your project, your rules. A rule is a `.py` file in `.schemalock/rules/`. The validator picks it up and runs it automatically.

A rule needs two things: an `EXTENSIONS` list and a `check(text, checker)` function. Report a violation with `checker.error(line, message)`. Violations go straight back to Claude, and Claude fixes them.

```python
import re

EXTENSIONS = [".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]

def check(text, checker):
    for n, line in enumerate(text.splitlines(), 1):
        if re.search(r"CREATE\s+TABLE\s+temp_", line, re.IGNORECASE):
            checker.error(n, "temp_ tables are not allowed")
```

Ready-made examples live in `.schemalock/rules_examples/` (`no_temp_tables.py`, `no_drop_table.py`). To use one, copy it into `.schemalock/rules/`. Examples that stay where they are do not run.

**Security:** rules are Python code, and they run on your machine. Only your own project's `rules/` folder is loaded. Never drop in a rule you have not read, and only take rules from sources you trust.

A broken rule does not stop the others. It is skipped with a warning on stderr.

## Known limits

SchemaLock is a static checker, and honest about it.

**It does not see:**
- TS/JS clients under other names (`tx`, `ctx.prisma`, `db`), generics like `findMany<...>`, clients assigned with a type annotation. In Python, `tx` is not seen either.
- Arguments held in variables, function parameters, or values coming from other files
- Python transactions and batches, `dict(role="X")`, URLs built from variables, Python clients imported from another file
- Enum values inside filter objects: `{ equals }`, `{ in }`, `{ not }`, `{ notIn }`
- Nested `connectOrCreate`, `upsert`, `createMany`, `update`, `updateMany`, `deleteMany`
- Fields inside composite keys (`@@id`, `@@unique`)
- axios instances, `axios.request(...)`, config-only `axios({ url })`, absolute `https://...` requests, other Python HTTP clients such as `httpx`
- `fetch` with a spread such as `{ ...opts, method: "X" }`
- Edits made through Bash (`sed`, `>`), and old code is not re-checked when the schema changes
- Multi-file Prisma schemas outside `prisma/schema/`
- SQLAlchemy-style attribute access such as `User.nonexistent_column`

**Python HTTP checks exist but almost never trigger:** `requests` does not accept relative URLs, and real code uses absolute or variable URLs.

**Things that can go wrong:**
- If either schema (Prisma or OpenAPI) cannot be read, validation is skipped entirely.
- Custom Python client names declared with `/// @Python(instance_name: ...)` are not recognized and may cause false alarms.
- If a project has an OpenAPI spec but no Prisma schema, `prisma.x.y(...)` calls are checked against the OpenAPI component schemas, which can cause false alarms.
- A compound key (`@@id`, `@@unique`) can be referenced by its generated name (for example `userId_postId`) or by its custom `name:`. Both are accepted, and the fields inside are not checked.
- For files outside the project folder, SchemaLock looks for the schema in the file's own folder and below it.

## Built to grow, and open to you

SchemaLock is young and built to be extended. Every limit above is an open door.

Want to help? Good places to start:

- **Protobuf and GraphQL support** (postponed, waiting for contributors)
- **More patterns**: aliased clients, variable arguments, more ORMs
- **Better Python HTTP checks**
- **Tests**: reverse tests, hook edge cases

Found a bug or have an idea? Open an issue or send a pull request. Every new pattern makes every AI-written line safer.

## License

MIT. See `LICENSE`.
