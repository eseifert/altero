# Contributing to altero

Help is welcome with testing, documentation, translations and code. Compatibility
with unmodified Zotero Desktop guides changes to the server.

## Reporting problems and suggesting changes

Use the [issue chooser](https://github.com/eseifert/altero/issues/new/choose)
for bugs and feature requests, or [Discussions](https://github.com/eseifert/altero/discussions)
for questions and setup help.

For bugs, include steps to reproduce, expected and actual behavior, and the
altero and client versions, operating system, database and deployment method.
Remove credentials and private content from logs and screenshots. For features,
describe the task you need to accomplish and any alternatives you tried.

You can help without writing code: review a guide as a first-time reader,
check a translation or [test with two desktop clients](docs/testing-two-clients.md).

## Getting set up

Use the Python and uv requirements in [pyproject.toml](pyproject.toml), and the
Node release in [web/.nvmrc](web/.nvmrc). Install the
[ICU build prerequisites](docs/deployment.md#from-a-source-checkout) first.

```sh
uv sync
uv run pre-commit install
cp config.example.py config.py
uv run alembic upgrade head
uv run altero
```

In another terminal, build or serve the browser interface:

```sh
npm --prefix web ci
npm --prefix web run dev
```

The API listens on port 8000; the development browser interface uses port 5173
and proxies API requests to it. To serve `/app/` from altero itself, run
`npm --prefix web run build`. Generated assets are not committed.

## The one architectural rule

Only `src/altero/api/` may depend on the web framework. Services take database
sessions and plain values, and raise domain errors from `errors.py`.
`api/errors.py` translates those errors into HTTP responses.

This keeps business rules testable without requests. The architecture check
walks imports; add a legitimate server-starting module to its explicit allowlist
instead of weakening the rule.

## Deciding what the right behavior is

Compare the live Zotero API, the official
[dataserver](https://github.com/zotero/dataserver), and the desktop client's
behavior. Use the published documentation as a guide, but when it disagrees
with the dataserver, preserve what the client expects.

Read [Compatibility](docs/compatibility.md) and [Database schema](docs/schema.md)
before changing surprising behavior. Record a deliberate difference and its
reason in the compatibility reference; put source paths and detailed code
evidence in comments or tests.

## Tests

Run checks appropriate to your change:

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run ty check
npm --prefix web test
npm --prefix web run typecheck
```

For bug fixes, prove the regression test fails without the fix. Test pure
rules without a database, service behavior at the service layer, and HTTP
behavior through the app. Request-path changes also need a real HTTP check.
Name tests for the behavior they protect.

### PostgreSQL

Concurrency tests skip without a disposable PostgreSQL database. For a local
container, use the PostgreSQL image selected by `docker/compose.yaml`:

```sh
docker run -d --name altero-pg -e POSTGRES_PASSWORD=altero \
    -e POSTGRES_USER=altero -e POSTGRES_DB=altero -p 55432:5432 <postgres-image>
export ALTERO_TEST_POSTGRES_URL=postgresql+asyncpg://altero:altero@localhost:55432/altero
uv run pytest -q tests/test_concurrency.py
```

Replace `<postgres-image>` with that image name. If the test container already
exists, start it instead of creating another.

> [!WARNING]
> These fixtures drop and recreate tables. Never point them at a database holding a real library.

### Identity and authorization

Real provider tests use disposable Keycloak and SimpleSAMLphp services:

```sh
docker compose -p altero-idp-tests -f tests/idp/compose.yml up --build -d --wait
export ALTERO_TEST_KEYCLOAK_URL=http://127.0.0.1:18080
export ALTERO_TEST_SIMPLESAMLPHP_URL=http://localhost:18081
uv run pytest -q tests/test_keycloak.py tests/test_keycloak_protocol.py tests/test_simplesamlphp.py tests/test_sso_keycloak.py
docker compose -p altero-idp-tests -f tests/idp/compose.yml down
```

Keep ports 18080, 18081 and 18765 free and run these tests serially.
Unset provider URLs cause skips; a configured but unavailable provider fails.
The fixtures use public test credentials and are unsuitable for real accounts.
See [fixture details](tests/idp/README.md).

`uv run pytest -q tests/test_authlib.py` tests the reverse direction, with
Authlib as an independent client of altero. It uses live HTTP on port 18765
and needs no external provider.

### Desktop and browser acceptance

When changing client-consumed responses, use the separate
[desktop compatibility suite](docs/client-compatibility.md). Source replay and
real desktop acceptance supply different evidence; report which one ran.

Browser end-to-end tests use Playwright against a real server. Build the
interface first, then run `npm --prefix web run e2e`.

## Commits

Keep each commit focused and explain why the change is needed. Include the
upstream evidence when it settles an ambiguous compatibility decision.
Pre-commit runs lint fixes and formatting; if it changes a file, review and
stage it again before retrying the commit.

## Adding an endpoint

1. Check the expected response against upstream.
2. Put business rules in services and HTTP handling in `api/routes/`.
3. Update the route inventory in `tests/test_routes.py`.
4. Add behavior checks and update [What works](docs/status.md).

Browser writes use CSRF protection. Browser sessions must never authenticate
the Zotero API. See the [authentication boundary](docs/compatibility.md#a-second-credential-for-the-v3-api).

## Changing the database

Add a migration; do not rewrite an existing revision. Existing installations
must be able to reach the new schema from their recorded revision.

Models live in `src/altero/models/` and are re-exported from its `__init__.py`
so Alembic sees them. Start with a database already at the current head:

```sh
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
uv run alembic check
```

Review generated migrations. Check both SQLite and PostgreSQL, including
populated upgrades when existing data is affected.

### Beta upgrade validation

The upgrade runner replays the historical beta tags available locally:

```sh
git fetch --tags
uv run --no-sync --with httpx==0.28.1 python -m tools.upgrade_paths \
  --state-dir /tmp/altero-upgrades \
  --postgres-url postgresql+asyncpg://altero:altero@localhost:55432/altero
```

Use a fresh state directory. `--tag <release-tag>` selects one starting release;
omitting PostgreSQL runs SQLite only. The runner creates fresh databases and
preserves logs, snapshots and `report.json` for inspection.

It checks a fixed populated corpus over real HTTP: objects, versions, permissions,
searchable text, attachment bytes, later writes and repeat startup. It uses
installed dependencies, not historical locks, and does not replace desktop
acceptance. See [recorded results](docs/release-history.md#recorded-upgrade-matrix).

## Documentation

The site is built from `docs/` and `zensical.toml`:

```sh
uv sync --group docs
uv run zensical serve -a localhost:8001
uv run zensical build --strict
```

Give each page one audience and lead with what readers need to do. User guides
explain tasks and outcomes; operator guides explain setup, consequences and
recovery; contributor references retain technical contracts and verification
limits. Link to a single explanation instead of repeating it.

Keep release numbers out of general instructions and feature descriptions.
Use configuration files for tool requirements and placeholders for chosen
release tags. Exact versions belong in the changelog and historical validation
records, where they identify what was actually tested.

Use GitHub callouts such as `> [!WARNING]` so pages render on both GitHub and
the site. Every site page belongs to one of the six navigation categories in
`zensical.toml`. Check links and anchors after moving or renaming sections.

### One English

Use American English and copy interface labels exactly from `en-US.ts`.
Write prose dates as `YYYY-MM-DD`. Preserve identifiers, filenames and quoted
upstream text as written.

### Translating the interface

Catalogs live in `web/src/locales`; `en-US.ts` defines the message keys.
Use natural, concise wording and Zotero's vocabulary for library objects.
Preserve placeholders, script and the language's established form of address.
Warnings must say whether content goes to Trash or is permanently deleted.

| Language | Existing convention |
| --- | --- |
| German | Neutral wording where possible; formal Sie/Ihr when addressing the reader |
| Dutch | Formal u/uw; notes are aantekeningen |
| Spanish | Formal usted; neutral action labels may use infinitives |
| Polish | Informal address; lowercase pronouns within sentences |
| Afrikaans | Formal u |
| Serbian | Cyrillic prose and controls; preserve product names and identifiers |
| Tagalog | Keep established loanwords such as library, email, password and time zone |
| Portuguese | Preserve regional terms, including Brazilian sobrenome and European apelido |

Use complete creator-name labels: they are also accessible input names.
Keep third-person descriptions and quoted interface labels intact. English-looking
acronyms and shared words need review, not automatic replacement.

Plural messages need the target language's forms, not English's count, with
matching placeholders in every branch. `web/src/i18n.ts` selects them; the catalog
tests check their counts. Arabic has six forms, Hebrew three, and Persian and
Shahmukhi Punjabi two with zero grouped with one.

To add a language, add its catalog, the server tag in `services/locales.py`,
the browser entry in `web/src/i18n.ts`, and any plural rule it needs. Preserve
regional and script matching in both server and browser. Item types, fields
and creator roles come from Zotero's schema rather than these catalogs.

Run the catalog checks and affected locale-specific browser assertions.
For a new plural rule, add rendered count examples as well. Passing these
checks verifies structure; native-speaker review is still needed for wording.

### How a version gets published

The docs workflow publishes master as `dev`, stable tags under their major/minor
series, and prerelease tags under their full release name. Stable releases move
the site's `latest` alias; prereleases do not. Before a stable release exists,
the development site may hold the alias. Link to `latest` for general release docs.

Publishing uses the Zensical-aware [mike fork](https://github.com/squidfunk/mike)
and the `gh-pages` branch. GitHub Pages must serve that branch's root.
The [workflow](.github/workflows/docs.yml) defines the publication rules.

## Preparing a release

1. Set matching versions in `src/altero/__init__.py`, `web/package.json` and both root entries of `web/package-lock.json`. Use Python's PEP 440 spelling and the corresponding SemVer spelling. Update the release-stage classifier in `pyproject.toml`; its version is dynamic and `uv.lock` has no project version.
2. Move unreleased changes into a dated changelog section, leaving an empty **Unreleased** heading. Add the release link. Keep changelog list items consecutive. Update guides for changed behavior without adding a current-release announcement to each one.
3. Set `release_tag` to the intended tag, then run the checks below with disposable PostgreSQL and identity providers configured.

   ```sh
   release_tag=...  # Replace with the full intended tag, including its v prefix.
   uv run python tools/release.py --tag "$release_tag"
   uv run ruff format --check .
   uv run ruff check .
   uv run ty check
   uv run pytest -q -rs
   uv run zensical build --strict
   npm --prefix web run typecheck
   npm --prefix web test
   npm --prefix web run build
   release_artifacts=$(mktemp -d /tmp/altero-release.XXXXXX)
   uv build --out-dir "$release_artifacts"
   uv run python tools/release.py --tag "$release_tag" --artifacts "$release_artifacts"
   ```

4. Check empty-database migrations with `alembic upgrade head` and `alembic check`, then run the [populated upgrade matrix](#beta-upgrade-validation). Review or rerun the relevant [desktop checks](docs/client-compatibility.md) and record their scope accurately.
5. Extract the wheel into an isolated directory, put it before the editable checkout on `PYTHONPATH`, and serve it against disposable state. Verify `/health`, `/app/`, referenced assets, a font, and authenticated API reads and writes over real HTTP.
6. Commit and push the preparation. Wait for CI before creating and pushing the matching annotated tag.

Build the interface **before** Python artifacts. Both Hatch targets must include
`src/altero/web/static/**`: the wheel is built through the source archive.
Preserve the source archive's public-path selection and the release checker's
inventory so local notes cannot enter a release. Keep artifacts and disposable
state under `/tmp` or ignored paths.

Tags publish container images and documentation, not a GitHub Release or Python
package upload. Container `latest` includes prereleases; documentation `latest`
does not. If making a GitHub Release, use its changelog section and mark its
release stage correctly. Publication workflows reject mismatched metadata.

Historical results are in [Release validation history](docs/release-history.md).
Do not relabel an old desktop or Podman run as evidence for a newer candidate.

## Before opening a pull request

- Keep the change focused and explain the resulting behavior and its reason.
- Run the relevant checks and report failures, skips and untested limits.
- Include a failing regression check for behavioral fixes.
- Update user documentation and the changelog when behavior changes.
- Keep generated browser assets, test data and local configuration out of the commit.
