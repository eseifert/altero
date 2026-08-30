# Contributing to altero

altero reimplements a protocol that other people's software already speaks. That
shapes almost everything below: the question is rarely "is this good design" but
"is this what the Zotero client expects".

## Getting set up

```sh
uv sync
uv run pre-commit install
cp config.example.py config.py
uv run alembic upgrade head
uv run pytest
```

Python 3.14 or newer, and [uv](https://docs.astral.sh/uv/). `pre-commit install`
is per-checkout and easy to forget; without it CI will fail on formatting you
could have fixed locally.

The concurrency tests need PostgreSQL, because SQLite has a single writer and so
cannot exhibit the races they cover. They skip without it, which is why CI
supplies one and fails if anything skipped:

```sh
docker run -d --name altero-pg -e POSTGRES_PASSWORD=altero \
    -e POSTGRES_USER=altero -e POSTGRES_DB=altero -p 55432:5432 postgres:18-alpine
export ALTERO_TEST_POSTGRES_URL=postgresql+asyncpg://altero:altero@localhost:55432/altero
uv run pytest
```

## The one architectural rule

`altero/api/` is the only package that may know about the web framework.
Everything else — `services/`, `query.py`, `search.py`, `pagination.py`,
`serializers.py`, `itemschema/` — takes a database session and plain values, and
reports failure with the domain errors in `errors.py`, which carry no HTTP
vocabulary. `api/errors.py` maps those onto status codes.

The point is not purity. It is that the interesting logic can be tested and
reasoned about without a request, and that replacing FastAPI would not mean
rewriting the server.

`tests/test_architecture.py` enforces this by walking the import graph. If you
add a module that legitimately starts the server, add it to `FRAMEWORK_MODULES`
there rather than loosening the check.

## Deciding what the right behavior is

Three sources, in decreasing order of authority:

1. **The running API** at `api.zotero.org`. Compare responses directly. This
   settles most questions in one request.
2. **The reference implementation**,
   [zotero/dataserver](https://github.com/zotero/dataserver) — mainly
   `model/API.inc.php`, `model/Items.inc.php`, `model/Tags.inc.php` and the
   controllers.
3. **The published documentation**, last, because it has been wrong more than
   once. It describes per-alternative negation in search expressions; neither
   the live API nor the implementation behaves that way.

Where the sources disagree, **the dataserver wins, even when it looks like a
bug** — the goal is a server the Zotero client works against, not a tidier API.
Mirrored quirks are recorded in [docs/compatibility.md](docs/compatibility.md)
with the source that settles them, and deliberate departures are recorded there
too, with the reason.

Read that file and [docs/schema.md](docs/schema.md) before "fixing" something
that looks wrong.

## Tests

**Write the test first, and make sure it fails.** A test that has never failed
is not evidence that anything works. When fixing a bug, revert the fix and watch
the test go red before you commit. This is not ceremony: it caught a concurrency
test on this project that passed just as happily with the bug present.

**Test through the layer the behavior belongs to.** Rules that are pure
functions of their input — search syntax, pagination arithmetic, key
validation — get unit tests with no database. Endpoint behavior gets tested
through an HTTP client against the app. Prefer the lower layer where there is a
choice; it is faster and the failure is easier to read.

**Do not stop at the test client.** Two real bugs on this project survived a
green suite and only appeared when a real server was driven with `curl`: child
items left pointing at a deleted parent, and an attachment template the server
itself would not accept back. If a change touches the request path, run the
server and use it.

**Name the behavior, not the function.** `test_negation_covers_every_alternative`
survives a refactor; `test_parse_expression_2` does not.

## Commits

One change per commit, with a message that explains **why**. The diff already
says what changed. What it cannot say is which of three plausible behaviors the
API actually has, or that a limit exists because the desktop client would
otherwise silently believe a library holds 25 objects.

If you found the answer in the dataserver or by measuring against a live
library, say so in the message. The next person will have the same doubt.

## Adding an endpoint

1. Check the shape against the live API before writing anything.
2. Put the behavior in `services/`, the routing in `api/routes/`.
3. Add it to the inventory in `tests/test_routes.py`. That test fails both when
   a route disappears and when an undeclared one appears — deliberately, because
   restructuring has twice dropped an endpoint silently. Under PEP 649 a
   dependency annotation that no longer resolves does not raise; FastAPI treats
   it as a missing query parameter and answers 400.
4. Update the status list in `docs/status.md`.

## Changing the database

Models live in `altero/models/`, one module per area, all re-exported from
`__init__.py` so that Alembic's autogenerate sees them.

**Add a revision; never rewrite an existing one.** There are databases holding
real libraries now, and a database remembers the revision it was stamped with.
Deleting that revision strands it: `alembic upgrade head` then fails with
"Can't locate revision", and no upgrade path exists. That has already happened
once on this project.

Autogenerate against a database already at `head`, or it re-detects the existing
tables:

```sh
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head   # apply it
uv run alembic check          # what CI runs; passes only when they agree
```

Read the generated revision before committing it. Autogenerate misses some
changes and guesses at others, and on SQLite it emits `batch_alter_table` blocks
that are worth a look.

Keep to portable constructs. SQLite is the default and PostgreSQL is the
supported deployment, so nothing may depend on features of one alone.

## Documentation

The pages under `docs/` are the documentation site at
<https://eseifert.github.io/altero/>, built by [Zensical](https://zensical.org)
from `zensical.toml` in the repository root. They are also read on GitHub, which
is why they keep GitHub's own callout syntax (`> [!WARNING]`) rather than
Markdown admonitions: the `github-callouts` extension turns those into
admonitions for the site, so one source renders properly in both places.

```sh
uv sync --group docs
uv run zensical serve -a localhost:8001  # rebuilds as you type; :8000 is
                                        # the altero server's own port
uv run zensical build --strict          # what CI runs
```

`--strict` fails on a link to a page that no longer exists or an anchor that was
renamed. Run it after moving anything in `docs/`.

The navigation is six categories, defined by `nav` in `zensical.toml`, and a new
page belongs in one of them: **Overview**, **Get started**, **Using altero**,
**Running altero**, **Reference**, **Contributing**. A page left out of `nav` is
still built and still reachable by link, but nothing leads to it.

### One English

The pages are written in American English, and so is every other page in the
repository that somebody reads: `-ize` and `-ization`, *behavior*, *color*,
*license* as both noun and verb, *catalog*, *gray*, *analyze*, *defense*,
*judgment*, *labeled*.

That is not a preference about English. `web/src/locales/en-US.ts` is the
canonical catalog every other one is checked against, `web/src/i18n.ts` falls
back to it, and a bare `en` resolves to it, so American is what the interface
says when nobody has chosen otherwise. `en-GB.ts` renames the Trash to the Bin
and *Choose a License* to *Choose a Licence*; a page written in British English
would name buttons that most readers do not have. It is also the language of
everything the pages quote — the `Authorization` header, `/oauth/authorize`,
and Zotero's own schema, API and dataserver — so the alternative is
code-switching every other sentence.

Three things follow. A string quoted from the interface is copied from
`en-US.ts` exactly, whatever it spells. A date written in prose is ISO-style,
`2026-08-28`, so it does not depend on where the reader is. And identifiers,
headers, file names and quoted upstream text are left alone: `loginCancelled`
is a name in the client, not a spelling.

### How a version gets published

`.github/workflows/docs.yml` publishes to the `gh-pages` branch on every push to
master and on every `v*` tag, using [mike][mike] — squidfunk's fork of it, which
drives Zensical rather than MkDocs. Zensical will grow versioning of its own, at
which point this goes away.

| What was pushed                 | Published as                  | `latest`                          |
|---------------------------------|-------------------------------|-----------------------------------|
| master                          | `dev`                         | only until a release is published |
| `v1.0.0`, `v1.2.3`              | `1.0`, `1.2`                  | yes                               |
| `v1.0.0-alpha.2`, `v1.0.0-rc.1` | `1.0.0-alpha.2`, `1.0.0-rc.1` | no                                |

A patch release replaces the pages it corrects rather than adding a version
nobody has a reason to choose between, so `v1.2.3` publishes as `1.2`. `latest`
is the alias the site's root redirects to, and it is what a link into the
documentation should use.

Releasing 1.0.0 takes nothing beyond tagging it. Which version holds `latest` is
read off the deployed site rather than off the tags, so the release takes the
alias over and master stops claiming it on its own.

The one thing that is not in the repository is the GitHub setting: **Settings →
Pages → Build and deployment → Deploy from a branch → `gh-pages` / (root)**.
Aliases are deployed as copies rather than symbolic links, because Pages refuses
to build a branch that contains one; identical files are a single git object, so
the copies cost nothing.

[mike]: https://github.com/squidfunk/mike

## Before opening a pull request

```sh
uv run ruff format .
uv run ruff check --fix .
uv run ty check
uv run pytest
```

CI runs the same checks, plus PostgreSQL for the concurrency tests and
`alembic check` for schema drift. It fails if any test skipped, so a green run
locally without `ALTERO_TEST_POSTGRES_URL` set is weaker evidence than it looks.

If you changed observable behavior, say in the pull request how you established
what the behavior should be. "The documentation says so" is not sufficient on
its own — see above.
