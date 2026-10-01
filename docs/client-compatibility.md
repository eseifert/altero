# Checking desktop compatibility

Run the optional compatibility suite when changing responses or versions that
Zotero Desktop consumes. It feeds altero API responses into original desktop
functions, and inventories source expectations to find contracts worth testing.

The normal `uv run pytest` suite needs neither Node nor a desktop checkout.
This toolchain needs Node 24+ and the Zotero revision pinned in
`tools/compatibility/contracts.toml`. Its only npm dependency is the JavaScript
parser; the server and its wheel gain no dependency.

## Set up the checkout

From the altero repository root, install the parser and clone a separate
desktop checkout:

```sh
npm --prefix tools/compatibility ci
git clone https://github.com/zotero/zotero.git .compatibility/zotero
uv run python - <<'PY'
import subprocess
import tomllib
from pathlib import Path
manifest = tomllib.loads(Path("tools/compatibility/contracts.toml").read_text())
subprocess.run(
    ["git", "-C", ".compatibility/zotero", "checkout", manifest["zotero"]["revision"]],
    check=True,
)
PY
```

An existing clean checkout at that revision works too; substitute its path in
the commands below. Verification checks the commit, tracked changes, complete
source-file fingerprints, and function selectors:

```sh
uv run python -m tools.compatibility verify --zotero-source .compatibility/zotero
uv run pytest -q compatibility_tests --zotero-source .compatibility/zotero
```

`ALTERO_ZOTERO_SOURCE` supplies the test suite's default path. Missing source,
Node, dependencies, or selectors fail the checks rather than skipping them.
The ignored `.compatibility/` directory holds checkouts and generated reports.

## What the executable contracts cover

| Contract | Original desktop code | Behavior checked |
|---|---|---|
| Group permissions | `getPermissionsFromJSON` | Members, administrators, group policies, files and read-only restrictions, through both group endpoints |
| Group refresh | `checkLibraries` and `Group.fromJSON` | A cached client fetches changed permissions after an API or command-line change moves the advertised version |
| Sync versions | `getVersions` and `_parseJSON` | A version listing carries its watermark, and a 304 is accepted without a body |

Functions are selected by JavaScript syntax nodes and executed in a Node
subprocess. Their decision logic keeps JavaScript's types, defaults and branch
order. The adapters provide HTTP response facades, in-memory persistence, and
small runtime helpers. The sync-version adapter substitutes the URI builder;
it checks the original response handling and request parameters. The group
refresh tests capture responses over a real HTTP socket.

The adapters do not run Zotero's database, application UI or full sync engine.
Group-removal prompts require the desktop runtime and raise an explicit error.
Continue to use [two-client testing](testing-two-clients.md) for complete
synchronization and convergence.

The harness was checked against PR #14's failure: removing the roster arrays
makes the permission checks fail, and omitting the command-line version
increment makes the refresh check fail. Source discovery also reports `admins`
and `members` when given altero's actual pre-fix serializer.

## Discover contracts from source

Inspect the scenario inventory before extending coverage:

```sh
uv run python -m tools.compatibility coverage \
  --output .compatibility/coverage.json --markdown .compatibility/coverage.md
```

`tools/compatibility/surface.toml` records executable, pending, desktop-runtime
and deliberately unsupported scenarios. Executable means test code exists;
the test run supplies the result. Counts describe scenarios, not a percentage
of API compatibility. Discovery also scans item, collection and search
serialization and the streaming client.

```sh
uv run python -m tools.compatibility analyze \
  --zotero-source .compatibility/zotero \
  --output .compatibility/report.json \
  --markdown .compatibility/report.md \
  --evidence .compatibility/evidence.json
```

The manifest maps selected consumers to server functions and defines the file
globs to inspect. The inventory includes direct input reads and simple aliases,
defaults, conditions, request construction, response headers and declared routes.
Constructed request paths are matched to route patterns where their literal
parts agree. These matches supply provider code for review.

Mapped input reads are compared with the possible fields of a returned Python
object, including dictionary aliases and conditional additions. An unknown
expansion or helper result remains unresolved. Each observation carries source
positions; unmapped consumers and parse errors stay in the report.

Read the report statuses as follows:

| Status | Meaning |
|---|---|
| `candidate` | A client-read field has no known server emission; reproduce the effect |
| `no-static-gap` | The mapped fields are present in the static shape; behavior still needs tests |
| `execution-only` | An executable contract or helper has no static field comparison |
| `unresolved` | Source or a dynamic object shape prevents a comparison |

This is a syntactic inventory with limited alias resolution. It does not resolve
all calls, scopes, dynamically constructed paths, mutations, or runtime types.
A field's presence says nothing about its value or whether a route actually
supplies it for a particular requester. An empty findings list therefore does
not establish compatibility.

Discovery returns a report even with candidates or unresolved entries. Exit
code 2 means a prerequisite, pinned source, command, or output could not be
used. Executable tests supply the pass/fail check.

## Add automated source review

The evidence JSON is also the input to an optional review program. It includes
mapped consumer/provider code, conditions, known exceptions, and unmapped
consumers with any matched routes. Source bodies share a 64,000-character
budget; clipped blocks are marked `truncated`.

To invoke a reviewer of your choosing:

```sh
uv run python -m tools.compatibility analyze \
  --zotero-source .compatibility/zotero \
  --review-command 'your-review-program' \
  --output .compatibility/review.json \
  --markdown .compatibility/review.md
```

The program reads one JSON object from stdin and writes this shape to stdout:

```json
{
  "findings": [{
    "contract": "group_permissions",
    "summary": "A hypothesis about the client and server behavior",
    "client": {"file": "chrome/content/zotero/xpcom/data/groups.js", "line": 138},
    "server": {"file": "src/altero/serializers.py", "line": 109},
    "reproduction": "Setup, action, and expected client behavior"
  }]
}
```

Use `contract: null` for an unmapped consumer. References must fall within the
supplied source spans. Invalid output and process failures are reported; every
accepted finding stays `unverified`. The command receives a JSON protocol and
can wrap a local analyzer or a model service. No model provider is built in or
called by the default workflow, and generated tests or fixes are never executed
by this interface.

## Add a contract or update Zotero

1. Establish the behavior using the project's
   [compatibility reference](compatibility.md) and contributing rules. Record
   any deliberate exception with its reason.
2. Add the consumer's source path, unique selector, complete file SHA-256,
   server binding and test path to the manifest. `server.input` names the
   consumer parameter and `server.object` the response object to compare.
   Additional `evidence` entries supply related server functions.
3. Write a scenario using actual endpoint responses and the original function.
   Supply only the runtime facades it needs in `adapters.mjs`.
4. Prove the check fails with the defect restored. Test transitions as well as
   fresh responses when the client caches a decision.

For a new desktop revision, first run discovery against a separate checkout
with `--allow-source-drift`. The report marks mismatched revisions or fingerprints
as unpinned. Review the changed functions and adapters before updating the
manifest's commit and hashes together, then run verification and every contract.
This flag is for discovery; executable checks always enforce their fingerprints.

## CI reports

The **Desktop compatibility** workflow replays the pinned contracts on pushes
to master and pull requests. It fails if a test skips and uploads the test
results, source report and review evidence. Static candidates remain review
work rather than reproduced failures.

A weekly and manually dispatched job also inspects Zotero's current `main`
with source drift allowed and uploads a separate upstream report. It does not
change the supported baseline or run an external review provider.
