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
| Group listing | `getGroups`, `getPaginatedResults`, `_parseLinkHeader` | Empty, single-page and multiple-page results remain readable in account preferences |
| Sync versions | `getVersions` and `_parseJSON` | A version listing carries its watermark, and a 304 is accepted without a body |
| Live sync reads | API key, settings, deletion, keys, versions and object-download methods | Personal and group libraries, restricted key flags, Unicode, incremental reads, trash, parent/child objects, missing keys and 99/100/101-object download batches |
| Live sync writes | Object/settings uploads and deletions | Mixed successful/unchanged/failed results, stale library and object versions, absent versus empty properties, trash/restore/delete sequences, deletion logs, 49/50/51-object writes and recovery after a committed write loses its response |
| Schema corpus | Generated from the vendored schema, through original API downloads | All 40 item types, every listed field and creator role, Unicode, client timestamps, notes, attachments and annotations |
| HTTP policy | Original request and retry methods | Backoff, numeric and invalid Retry-After, increasing 429 delays, terminal errors and connection loss after a committed write; delays use a virtual clock |
| Full text | Full-text upload, read and version methods | Empty and Unicode content, client-selected gzip, missing content, incremental versions and stale writes |
| Files | Original ZFS transfer methods | Authorization, unauthenticated byte upload, registration, absolute download locations, MD5/mtime/compression metadata, ZIP snapshots and unchanged-file download avoidance |

The desktop sends partial object changes inside a `POST` batch. Its API helper
also accepts a `PATCH` method argument, but the sync engine uses `POST` and the
dataserver does not accept `PATCH` on the collection endpoint for items.
The field-clearing scenarios therefore exercise partial `POST` bodies.

Functions are selected by JavaScript syntax nodes and executed in a Node
subprocess. Their decision logic keeps JavaScript's types, defaults and branch
order. The adapters provide HTTP response facades, in-memory persistence, and
small runtime helpers. The sync-version adapter substitutes the URI builder;
it checks the original response handling and request parameters. The group
refresh tests capture responses over a real HTTP socket.

`tools.compatibility.live.DesktopAPI` executes the complete original
`syncAPIClient.js`, including URL construction, headers, gzip decisions and
retry policy, against a local HTTP server. Its async Python subprocess leaves
the server event loop free to answer requests. The transport supplies an XHR
response facade; the scheduler records requested delays without sleeping.
Request traces omit the API key. Injected responses and response mutations
exercise error handling without changing the pinned source.

`DesktopStorage` runs the original ZFS authorization, upload, registration and
download methods through the same transport. In-memory facades supply file
attributes, bytes and persistence; downloaded metadata and bytes are captured
at the `processDownload` boundary. This does not test writing or unpacking files
in a desktop profile. A missing remote file exercises ZFS's settled-file path.

The schema corpus checks server wire round trips. Actual desktop serialization
and persistence belong to the disposable-profile acceptance runner.

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

## Cross-check the dataserver reference

Pass `--dataserver-source /path/to/dataserver` to `verify` and `analyze`.
`tools/compatibility/reference.toml` pins the independent reference revision,
complete source hashes and reviewed PHP spans for group pagination, write
results and limits, partial batches, deletions, settings, full text and storage.
Verification fails on revision, tracked changes, hashes or invalid spans.
The report includes the source comparison and the review packet includes bounded
reference evidence. PHP is inspected, not executed; this is not a live
api.zotero.org differential test.

The comparison records two deliberate differences relevant to these scenarios:
altero substitutes a `self` Link for upstream's zotero.org `alternate`, and
retains one library version per changed request, while this dataserver revision
bumps per object and commits a bump for unchanged objects. Full-text versioning
already has the same documented per-request distinction. Compare object state
and monotonic watermarks rather than expecting equal counter values.

The reusable `LibraryReplay` helper and `disposable_server` support standalone
sequence and desktop acceptance commands. The latter creates a new database and
file store, binds only loopback, seeds a disposable test credential, and closes
the server when the run finishes. It refuses an existing state directory.

`generate_sequence(seed, steps)` produces valid create/edit/file/unfile,
trash/restore and delete operations. Tests run seeds 4, 14 and 91 in personal
and group libraries, checking an independent state model after every step.
`minimize` removes chunks while preserving a caller-defined failure predicate;
invalid sequences must be rejected rather than treated as reproductions.

Run and replay a standalone sequence with preserved disposable databases:

```sh
uv run python -m tools.compatibility sequence --zotero-source .compatibility/zotero \
  --seed 14 --steps 30 --state-dir .compatibility/sequence-14 \
  --output .compatibility/sequence-14.json
uv run python -m tools.compatibility sequence --zotero-source .compatibility/zotero \
  --replay .compatibility/sequence-14.json --state-dir .compatibility/replay-14 \
  --output .compatibility/replay-14.json
```

Failures automatically shrink against fresh servers, rejecting invalid operations
and preserving the failing invariant. The JSON keeps the seed, original operations,
failure and independently confirmed minimized sequence. Exit 1 is a reproduced
assertion failure; prerequisites and runner errors remain exit 2. Replays require
a new state directory.

`desktop.prepare_profile` installs a small acceptance add-on in a new profile
and data directory. It points the desktop at a disposable server, disables
automatic sync, streaming, updates and word-processor installation, and leaves
sync logic intact. `run_phase` applies explicit operations through Zotero's
item APIs, runs the real sync runner, exports a JSON snapshot and exits. Each
phase enforces the requested application version and a timeout, and preserves
the desktop log on failure. The installed Zotero 10.0.1 completed a real
create-and-upload smoke test; its binary version is separate from the pinned
source revision used by Node replay.
