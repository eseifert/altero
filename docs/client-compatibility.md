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
This layer checks the API scheduler; generic retry behavior inside
`Zotero.HTTP.request` is provided by the facade and is not exercised here.
Request traces omit the API key. Injected responses and response mutations
exercise error handling without changing the pinned source.

`DesktopStorage` runs the original ZFS authorization, upload, registration and
download methods through the same transport. In-memory facades supply file
attributes, bytes and persistence; downloaded metadata and bytes are captured
at the `processDownload` boundary. This does not test writing or unpacking files
in a desktop profile. A missing remote file exercises ZFS's settled-file path.

The schema corpus checks server wire round trips. Actual desktop serialization
and persistence belong to the disposable-profile acceptance runner.

Source replay adapters provide facades for the database and application UI.
The real acceptance runner below exercises complete synchronization separately.
Group-removal prompts raise an explicit error in source replay; continue to use
[two-client testing](testing-two-clients.md) for interactive conflict dialogs
and removal prompts.

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

A nightly and manually dispatched job also inspects Zotero's current `main`
with source drift allowed and uploads a separate upstream report. It does not
change the supported baseline or run an external review provider.


CI now verifies the pinned dataserver checkout alongside the desktop source and
attaches the reviewed reference spans to its reports. It uploads the scenario
inventory beside JUnit, and runs the mutation catalogue nightly and on manual
dispatch. Write, full-text, pagination, HTTP-policy and storage-registration
consumers now have explicit manifest selectors as well as live scenario tests.

The real desktop CI job is opt-in: configure repository variables
`ZOTERO_DESKTOP_URL`, `ZOTERO_DESKTOP_SHA256` and `ZOTERO_DESKTOP_VERSION` for a
pinned official Linux archive. It checks the archive hash and running version,
runs under Xvfb, and uploads snapshots, logs and desktop databases even on failure.
The variables are deliberately unset by default. The local installed 10.0.1
binary was tested; its proposed official archive URL returned 403, so no download
URL or checksum is presented as verified. The GitHub jobs themselves have not
been executed locally.

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

## Generated sequences and replay

The reusable `LibraryReplay` helper and `disposable_server` support standalone
sequence and desktop acceptance commands. The latter creates a new database and
file store, binds only loopback, seeds a disposable test credential, and closes
the server when the run finishes. It refuses an existing state directory.

`generate_sequence(seed, steps)` produces valid create/edit/file/unfile,
trash/restore and delete operations. Tests run seeds 4, 14 and 91 in personal
and group libraries, checking an independent state model after every step.
`minimize` removes chunks while preserving a caller-defined failure predicate;
invalid sequences must be rejected rather than treated as reproductions.
Validity includes an actual state change: removing a trash step must not turn
a later restore into a no-op that is mistaken for the original failure. Empty
or ineffective replay input is rejected before creating a server.

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

A live check injected a frozen watermark into seed 14 with six operations.
The runner reduced it to one create operation and confirmed the same invariant
on a fresh server in four trials.

## Run two real desktop profiles

`desktop.prepare_profile` installs a small acceptance add-on in a new profile
and data directory. It points the desktop at a disposable server, disables
automatic sync, streaming, updates and word-processor installation, and leaves
sync logic intact. `run_phase` applies explicit operations through Zotero's
item APIs, runs the real sync runner, exports a JSON snapshot and exits. Each
phase enforces the requested application version and a timeout, and preserves
the desktop log on failure. The installed Zotero 10.0.1 completed a real
create-and-upload smoke test; its binary version is separate from the pinned
source revision used by Node replay.


```sh
uv run python -m tools.compatibility acceptance \
  --desktop-executable /opt/zotero/zotero --desktop-version 10.0.1 \
  --xvfb --schema-corpus --state-dir .compatibility/desktop-10.0.1
```

This requires an installed Zotero binary and Xvfb (or omit `--xvfb` to use an
existing display). The version is checked by the running application. The
command creates two isolated profiles and a loopback server, drives the actual
sync engine and ZFS filesystem path, and preserves phase snapshots, databases
and logs. It refuses an existing state directory.

To exercise PostgreSQL, add
`--postgres-url postgresql+asyncpg://altero:altero@localhost:55432/altero`.
The existing container can supply this connection. The account must be allowed
to create databases: every scenario creates its own `altero_acceptance_<uuid>`
database and leaves the database named in the URL untouched. Each scenario's
`server/database.json` records the generated name without credentials. Databases
are retained on success and failure for inspection; drop those generated
databases explicitly when finished. Desktop profiles and files remain under
the new state directory. Without the flag the server uses SQLite there.

The 15-phase run passed locally with Zotero 10.0.1: parent/note/file download,
collection filing, persisted attachment bytes, disjoint offline edits and
convergence, trash/restore propagation, deletion of parent and children, and
all 40 schema types serialized by desktop A and downloaded into desktop B.
The schema phase disables file transfer because its generated attachment has
metadata only; the preceding file scenario checks real byte transfer.
The acceptance command also runs same-field conflicts in a separate pair of
profiles. It selects the local and remote panes in the actual merge dialog and
clicks Finish, checks both desktops against the server and requires another sync to
leave the library watermark unchanged. Unexpected or missing dialogs fail the
phase; prompt/reconciliation methods are never replaced.

Each desktop has its own temporary directory and waits for schema/bundled-file
initialization before running operations. This avoids shared translator staging
files and shutdown racing unfinished startup work.

Use `--scenario baseline` or `--scenario conflicts` to run one scenario; repeat
the flag to select several. The default runs every implemented scenario, each
with its own profiles and server under the new state directory. The top-level
`acceptance.json` records scenario results and each subdirectory retains its
phase snapshots and desktop logs.

`--scenario groups` uses an owner and a member account. It checks member/admin
promotion and demotion, editing/file-policy changes and server denial after a
restriction. With pending local edits, the real permission-loss prompt's Skip
retains work and Reset restores server state. Membership removal exercises Keep
Group (archive locally, retaining unsynced data), rejoining and Remove Group.
The runner verifies both the dialog and the resulting persisted state. Policies
are cross-checked against `Group.inc.php` in the pinned dataserver; the prompts
and archival choices come from desktop `checkLibraries` and `checkLibraryForAccess`.
Group phases use the runner's ordinary all-library sync: explicitly forcing a
group library into its input list can make this client attempt an upload even
after Skip Group. The group selector scopes local operations and snapshots.

`--scenario files` replaces bytes of an existing attachment, exercises both file
conflict choices, removes a local file and calls the original on-demand download
to recover it after verifying that its missing state persisted.
It checks disk bytes, server downloads, synced hashes and settled storage states.
Offline edits run the original file-change scan before exiting the profile, so
pending uploads are persisted before incoming metadata arrives. File conflicts
overlap real syncs: B pauses just before upload authorization, A commits its file,
then B continues with its stale hash. No response or sync method is mocked.
The files have a one-hour timestamp offset, which Zotero's timestamp check
tolerates, keeping the local file until ZFS compares hashes. After selecting
the local side, A's stale copy is removed and downloaded on demand. This
explicitly covers recovery rather than claiming the client
detects every timestamp collision. With exactly equal displayed dates, the
client identifies either selection as local; that upstream ambiguity remains
unverified as a resolvable remote choice. A multi-file HTML snapshot also checks
that ZIP transfer restores its HTML and CSS on disk.

Acceptance phase snapshots also record collections, saved searches, pending
object uploads and group permissions. `AcceptanceRun` compares persisted objects
on both desktops with server responses, normalizing omitted empty/default
properties while retaining keys and versions. Matching item titles alone cannot
claim convergence. Its group selector requires discovery before local edits;
each profile's account identity is explicit.

`--scenario relationships` moves and renames a collection branch, reparents a
note and a file attachment, changes a book into an article, replaces a saved
search's conditions, edits an annotation's comment, color and position, and
clears tags and collection membership. Both desktops' persisted objects must
match server responses after each transition. The annotation's parent is a
file attachment, as both desktop and dataserver require. This checks sync data
and caches; it does not open the reader or test rendered annotation images.

`--scenario recovery` kills desktop A after the server has committed an item
but before it sends the response. Restarting the same profile must settle the
pending upload without duplicating the commit. Both real runners then upload
disjoint pending work simultaneously, converge and leave the watermark unchanged
on another sync. Finally B is killed after receiving part of an attachment
download; restarting must recover all bytes and leave its storage state synced.
The HTTP barriers pause genuine requests and preserve their responses. The
server remains running: server-process crashes and interrupted uploads are
separate gaps. This scenario passed locally on PostgreSQL 18.4.

Streaming scenarios subscribe over a real WebSocket, make a live write and feed
the greeting, subscription changes and notification into the original `_connect`
message handler. They check sync scheduling, already-current and skipped libraries,
and reconnect delays. The replay supplies a socket facade and virtual clock;
actual desktop reconnect timing and UI scheduling are not exercised.

## Prove the checks detect omissions

```sh
uv run python -m tools.compatibility mutations --zotero-source .compatibility/zotero \
  --state-dir .compatibility/mutations --output .compatibility/mutations.json
```

Seven named mutations remove a watermark, truncate versions, omit a successful
write result, omit a deletion, ignore empty clearing properties, freeze the
watermark or remove the group roster. Every canary first has to pass intact,
then fail by assertion in every parametrized case. Setup errors, skips and
unrelated exceptions are rejected. JUnit and logs are preserved for each run.
All seven were detected locally, including PR #14's missing-roster class.

These are controlled protocol mutations at the transport boundary. The clearing
mutation removes empty properties before sending the request, simulating a writer
that ignores them; the others alter responses. They establish assertion strength,
not a mutation score for production source. `ALTERO_COMPAT_MUTATION` selects only
a catalogue entry and is normally unset.

The expanded local validation passed 146 compatibility tests and 231 architecture
checks under Node 24, with no skips. Ruff formatting/lint, type checking and the
strict documentation build passed. The source report verifies 30 client selectors
and 13 reviewed dataserver spans; its 21 unmapped consumers remain visible.
Those counts describe this baseline and do not certify the whole desktop surface.
