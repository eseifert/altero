# Contributing to altero

altero reimplements a protocol that other people's software already speaks. That
shapes almost everything below: the question is rarely "is this good design" but
"is this what the Zotero client expects".

## Getting set up

Install the [ICU build prerequisites](docs/deployment.md#from-a-source-checkout)
first (`libicu-dev pkg-config g++` on Debian or Ubuntu).

```sh
uv sync
uv run pre-commit install
cp config.example.py config.py
uv run alembic upgrade head
uv run pytest
```

Python 3.14.10 or newer, [uv](https://docs.astral.sh/uv/) 0.13.4 or newer, and Node
24.22.1 or newer for the web interface; see
[Deployment](docs/deployment.md#from-a-source-checkout) for why. `pre-commit install`
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

The identity-provider tests also need real Keycloak and SimpleSAMLphp services.
Their checked-in configuration contains public test credentials and exact
loopback callback addresses; use it only for disposable test directories.
Build the pinned SimpleSAMLphp fixture, start both providers and wait for
readiness before running the tests:

```sh
docker compose -p altero-idp-tests -f tests/idp/compose.yml up --build -d --wait
export ALTERO_TEST_KEYCLOAK_URL=http://127.0.0.1:18080
export ALTERO_TEST_SIMPLESAMLPHP_URL=http://localhost:18081
uv run pytest -q tests/test_keycloak.py tests/test_keycloak_protocol.py tests/test_simplesamlphp.py
docker compose -p altero-idp-tests -f tests/idp/compose.yml down
```

Keycloak uses port 18080, SimpleSAMLphp 18081, and the real altero server 18765,
all on loopback. Run these tests serially with those ports free. Each test gets
its own altero database and file store. Tests skip when their provider's URL
variable is unset; an unavailable service at a configured URL fails. CI starts
the same Compose services after checkout and requires these tests to run. See the
[fixture and coverage details](tests/idp/README.md).

The reverse direction uses Authlib as an independent OAuth/OpenID client:

```sh
uv run pytest -q tests/test_authlib.py
```

These 24 live HTTP cases need no external identity provider. They run in the
ordinary CI suite without an opt-in variable, using Authlib's native httpx2
integration and a fresh altero database per case. Keep loopback port 18765 free
and run serially with the provider tests. They cover code + PKCE, signed ID
tokens, userinfo, refresh rotation/replay, revocation, device consent and logout
for public clients and both confidential client authentication methods.

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

**Check what the desktop decides.** The optional
[desktop compatibility suite](docs/client-compatibility.md) executes original
Zotero functions on altero responses and inventories missing source contracts.
Use it when changing a client-consumed response or version. Its Node dependency
and pinned desktop checkout are separate from the normal Python tests.

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

### Beta upgrade validation

To replay upgrades from every local `v1.0.0-beta.*` tag with live HTTP:

```sh
git fetch --tags
uv run --no-sync --with httpx==0.28.1 python -m tools.upgrade_paths \
  --state-dir /tmp/altero-upgrades \
  --postgres-url postgresql+asyncpg://altero:altero@localhost:55432/altero
```

Use a new state directory each time; `--tag v1.0.0-beta.1` selects one release.
Without `--postgres-url`, only SQLite runs. The PostgreSQL connection creates
fresh `altero_upgrade_*` databases and never migrates the named admin database.
All databases, extracted tagged sources and logs remain available for inspection;
`report.json` records source commits, revisions and results. The runner uses the
installed dependencies, adding legacy `httpx` for the older application imports;
it does not reproduce historical dependency locks or build browser assets.
Each tagged server populates a personal and group library through real HTTP:
items, creators, tags, a note, nested collections, a saved search, settings,
trash, a deletion, full text, a plain file and a snapshot ZIP with an auxiliary
resource. The upgraded server must preserve their data, versions, searchable
text and downloaded bytes. Only the documented child-membership repair and
empty-creator response shape may differ. Existing API keys and read-only group
permissions must still work; a new write must advance once and a stale write
must fail. Repeating migrations and restarting must preserve the new state.
This is a fixed corpus, not coverage of every historical setting or credential;
actual desktop acceptance remains a separate check.

The migration CI job runs the full matrix and retains its JSON snapshots and
logs as `beta-upgrade-results`. On 2026-11-04, all fourteen local combinations
passed against target revision `b4e28a1c6709`:

| Starting release | Source commit | Starting revision | SQLite | PostgreSQL 18 |
|---|---|---|---|---|
| beta.1 | `f38036bdd8cf` | `d7cd57abc8a4` | pass | pass |
| beta.2 | `3c5963974153` | `d7cd57abc8a4` | pass | pass |
| beta.3 | `3299558b6af0` | `a3f1c6d2e8b4` | pass | pass |
| beta.4 | `11b928d4afc2` | `a3f1c6d2e8b4` | pass | pass |
| beta.5 | `8f1b1cf68d28` | `a3f1c6d2e8b4` | pass | pass |
| beta.6 | `9c0b5238536c` | `e5b8c1f07a26` | pass | pass |
| beta.7 | `920a388d75d7` | `e5b8c1f07a26` | pass | pass |

Nine deliberate losses were detected by assertion: item fields, note HTML,
child-membership repair, its watermark, a collection, settings, a deletion,
full text and downloaded attachment bytes. The byte check used a separate copy
over live HTTP; restoring its bytes made the intact snapshot pass again.
This local run does not establish a hosted CI result, historic dependency-lock
compatibility, downgrade safety or a full desktop acceptance run.

## Documentation

The pages under `docs/` are the documentation site at
<https://altero.run/>, built by [Zensical](https://zensical.org)
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

### Translating the interface

Prefer short, natural instructions and use Zotero's terms for library objects.
Preserve each language's existing form of address and fix inconsistencies
within it; do not impose one language's convention on the others.
The German catalog uses neutral wording where possible (for example,
“Jetzt kopieren”); when direct address helps, use formal “Sie” and “Ihr”
consistently. Keep third-person pronouns and quoted interface labels intact.
The catalog checks guard against informal German address alongside missing
messages, changed placeholders and incorrect plural counts.

Keep each catalog's script consistent, including strings taken from upstream.
Serbian uses Cyrillic for translated prose and controls; product names,
protocol identifiers, keyboard labels and quoted navigation labels retain
their original spelling. Creator-name hints describe given and family names,
not ordinal positions.

Use complete name labels even where upstream abbreviates them: the creator
editor uses those hints as accessible input names too. Keep regional vocabulary
such as Brazilian Portuguese `sobrenome` and European Portuguese `apelido`.

Text identical to English is a review candidate, not automatically a missing
translation: acronyms, key names and shared words may stay unchanged. Translate
instructions even when Zotero's own catalog still has an English fallback.
The merge-instruction checks cover that known gap; they do not establish a
complete linguistic review of every message.

In provider setup, local explanations can sit beside protocol terms such as
`Client ID`, `Client secret` and `Issuer`, so administrators can match the fields
to their provider's documentation.

Keep established software loanwords when they fit the catalog's prose. Tagalog
retains `library`, `email`, `password` and `time zone`; changing just one message
to another term makes the interface less consistent. Account labels and note
formatting tools still need natural local wording.

Dutch uses formal `u/uw`, including device and application-consent instructions.
Permissions name notes as `aantekeningen`, matching Zotero and the library
controls. Preserve that vocabulary when adding permission descriptions.

Spanish uses formal `usted`, with matching `su` and verb forms, across account,
library and publishing screens. Neutral action labels can use the infinitive.
Keep third-person descriptions intact: `pide un código` describes the sign-in
process, while `crea una clave` describes what linking Zotero does.

Plural messages need one branch per cardinal form of the target language,
including the same placeholders in every branch. Arabic uses six branches
(zero, one, two, few, many, other); Hebrew uses three (one, two, other).
Persian and Shahmukhi Punjabi use two and count zero with one. The selectors
in `web/src/i18n.ts` use CLDR categories in that order. Add catalogue checks
in `web/src/locales/locales.node.spec.ts` and rendered examples in the plural
tests when introducing another rule.

### How a version gets published

`.github/workflows/docs.yml` publishes to the `gh-pages` branch on every push to
master and on every `v*` tag, using [mike][mike] — squidfunk's fork of it, which
drives Zensical rather than MkDocs. Zensical will grow versioning of its own, at
which point this goes away.

| What was pushed                 | Published as                  | `latest`                          |
|---------------------------------|-------------------------------|-----------------------------------|
| master                          | `dev`                         | only until a release is published |
| `v1.0.0`, `v1.2.3`              | `1.0`, `1.2`                  | yes                               |
| `v1.0.0-beta.3`, `v1.0.0-rc.1`  | `1.0.0-beta.3`, `1.0.0-rc.1`  | no                                |

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

## Preparing a release

The release version is **1.0.0-beta.7**, with tag `v1.0.0-beta.7`.

1. Set the package version in `src/altero/__init__.py` (`1.0.0b7` in PEP 440).
   Set the matching SemVer version (`1.0.0-beta.7`) in `web/package.json` and
   both the top-level and root-package entries of `web/package-lock.json`.
   `pyproject.toml` reads the Python version dynamically; `uv.lock` carries no
   project version to change. Keep the development-status classifier in
   `pyproject.toml` consistent with the release stage.
2. Move the unreleased changes into a dated section of `CHANGELOG.md`, leaving
   an empty `Unreleased` heading above it. Add its release link at the bottom.
   Keep consecutive list items without blank lines. Update the README, release
   status and version examples in the deployment and configuration guides.
3. Check the release metadata and run the checks below, with PostgreSQL set up
   as described above. The concurrency fixtures drop and recreate tables: use
   a disposable test database, never an existing library database.

   ```sh
   uv run python tools/release.py --tag v1.0.0-beta.7
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
   uv run python tools/release.py --tag v1.0.0-beta.7 --artifacts "$release_artifacts"
   ```

   Install the docs group for Zensical and put Node 24 on PATH for the web
   commands. Build the web interface before the Python artifacts so the wheel
   contains `/app/`. Verify migrations on an empty disposable database with
   `uv run alembic upgrade head` and `uv run alembic check`. Rerun the
   [populated beta upgrade matrix](#beta-upgrade-validation) against the release
   candidate and review
   [desktop compatibility results and limits](docs/client-compatibility.md);
   API and source replay tests alone do not establish real desktop acceptance.

   The artifact check verifies that the wheel's browser index and its referenced
   files are present, that the source archive carries the same browser files,
   and that the archive includes only the project's declared public paths.
   A metadata check alone does not prove the built package is usable.
   Extract the wheel into an isolated directory and put it first on `PYTHONPATH`,
   ahead of the editable checkout. Start it against a disposable database and
   verify `/health`, `/app/`, the index's assets, a font and authenticated API
   reads and writes over real HTTP. Keep artifacts and disposable state under
   `/tmp` or ignored paths.

   Both Hatch build targets explicitly include the generated interface as
   [build artifacts](https://hatch.pypa.io/latest/config/build/#artifacts),
   because `uv build` builds its wheel through the source archive. Source
   archives select public project inputs; they do not select every workspace
   file. Keep that selection and the artifact check's public-path inventory
   aligned when adding a new top-level directory.
4. Commit the release preparation in small batches, including the relevant
   docs. Push master and wait for its CI checks before pushing the tag:

   ```sh
   git push origin master
   git tag -a v1.0.0-beta.7 -m "altero 1.0.0-beta.7"
   git push origin v1.0.0-beta.7
   ```

The tag publishes multi-architecture container images under `1.0.0-beta.7` and
`latest`, and documentation under `https://altero.run/1.0.0-beta.7/`. Prerelease
documentation does not take the docs site's `latest` alias; that policy is
separate from the image's `latest` tag. A tag does not create a GitHub Release
or upload Python packages. If creating a GitHub Release, mark it as a prerelease
and use the matching changelog section as its notes.

CI checks the release metadata on every change. Both tag publication workflows
also verify the pushed tag against the package, web manifests and changelog
before publishing an image or documentation. A mismatched tag fails publication.
The web CI job builds both Python artifacts after building the interface and
checks their actual contents, including rebuilding the wheel through the source
archive.

### Beta.7 validation

Local release checks on 2026-10-30 used Python 3.14.10, uv 0.13.6 and
Node 24.22.1:

- The full Python suite passed 3,452 tests with no skips or warnings, including
  concurrency checks against a fresh disposable PostgreSQL database.
- The pinned Zotero 10.0.7 source-replay suite passed 333 tests with no skips.
- Ruff formatting/lint, Ty, the locked dependency check and strict documentation
  build passed. The web interface passed 1,921 tests, types and production build.
- The complete Chromium suite passed 136 desktop/phone cases with no skips,
  failures or flaky results, including axe, fonts, RTL gestures and mixed text.
- Pinned Zotero and dataserver source verification passed for 31 client
  functions. The network-consumer review gate covered 324 files and 88 consumers,
  with no parse errors or stale reviews.
- Empty-database migrations and `alembic check` passed on SQLite and PostgreSQL,
  using separate disposable databases.
- A populated beta.6 SQLite database upgraded to the extracted beta.7 wheel.
  Items, note HTML, collections, settings, deletions, object and library versions,
  a search for `über`, and attachment download headers and bytes were unchanged.
  A subsequent write advanced the library by exactly one version.
- The wheel built through the source archive retained all 611 browser files.
  Real HTTP from its isolated extraction served `/health` (`1.0.0b7`), `/app/`
  with its Content-Security-Policy, the index's assets and a local font. The
  service worker and manifest required revalidation. Authenticated API reads
  and writes passed, including `sandbox` and `nosniff` headers, and a three-step
  attachment upload downloaded with identical bytes.

The [recorded desktop matrix](docs/client-compatibility.md#successfully-tested-matrix)
passed all 36 scenarios on both SQLite and PostgreSQL with Zotero 10.0.7 on
Linux: 72 combinations and 838 phases, including the schema corpus. Both
full runs used fresh state against the beta.7 release candidate on 2026-10-30.
Hosted CI and multi-architecture image publication still need checking after
pushing; no tag was created locally.

### Beta.6 validation

Local release checks on 2026-10-28 passed, on Python 3.14.10, uv 0.13.6 and
Node 24.22.1:

- The full Python suite: 3,227 tests, no skips and no warnings,
  including concurrency checks against a fresh disposable PostgreSQL database.
- The optional desktop source-replay suite: 323 tests, no skips, against the
  pinned Zotero 10.0.6 source.
- The web interface: 1,734 tests, types and production build, after `npm ci`
  installed exactly the lockfile. The end-to-end suite passed 78 tests in
  Chromium at desktop and phone sizes, including uploading, replacing and
  renaming a file and trashing and restoring a note under an item, with no
  Content-Security-Policy violation and no serious or critical axe finding.
- Pinned Zotero and dataserver source verification (30 client functions), plus
  the network-consumer review gate: 324 files, 88 consumers, no parse errors or
  stale reviews.
- Ruff formatting/lint, Ty, the locked dependency check and strict documentation
  build.
- Upgrades from beta.5: both migrations apply to a SQLite database created and
  filled by beta.5, and `alembic check` finds no drift. The first start renamed
  the stored web snapshot to the digest of its own bytes and a second start left
  it alone. Items with their versions, the library version, a setting, a
  deletion record, a search for `über` and both files' download headers and
  bytes were identical before and after, and a write moved the library on by
  one version.
- The wheel built through the source archive: all 587 browser files survived,
  and real HTTP from the extracted wheel served `/health` (`1.0.0b6`), `/app/`
  with its Content-Security-Policy, the index's assets and a font, and the
  service worker and manifest with `no-cache`. Authenticated API reads and
  writes passed, with `sandbox` and `nosniff` on their answers, and a file
  uploaded by the three-step protocol downloaded with the same bytes.

The [recorded desktop matrix](docs/client-compatibility.md#successfully-tested-matrix)
has 68 SQLite/PostgreSQL combinations and 794 phases with Zotero 10.0.6 on Linux,
run against the release candidate: all 34 scenarios pass on both databases, each
database in a single run. Remote CI and multi-architecture image publication
must still be checked after pushing.

## Before opening a pull request

```sh
uv run ruff format .
uv run ruff check --fix .
uv run ty check
uv run pytest
```

CI runs the same checks, plus PostgreSQL for the concurrency tests, Keycloak and
SimpleSAMLphp for identity-provider tests, and `alembic check` for schema drift.
It fails if any test skipped. Each service's tests skip locally when its
corresponding `ALTERO_TEST_*_URL` variable is unset.
The separate Desktop compatibility workflow runs the optional contracts and
uploads discovery reports; its scheduled job also inspects upstream changes.

If you changed observable behavior, say in the pull request how you established
what the behavior should be. "The documentation says so" is not sufficient on
its own — see above.

The optional desktop suite now includes generated schema payloads, seeded
transition sequences with replay/shrinking, storage and full-text transfers,
streaming decisions and known protocol mutations. See
[the compatibility commands](docs/client-compatibility.md) for the pinned
dataserver cross-check and the disposable two-profile desktop runner. Every
compatibility batch should update the documented scenario inventory and limits.
