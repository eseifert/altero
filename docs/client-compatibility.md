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

The network inventory scans all JavaScript and modules under the pinned desktop's
`chrome/content` and `resource` trees, including JSX, anonymous callbacks and
file-level requests. It includes HTTP helpers, file downloads, fetch, XHR and
WebSocket construction. Every discovered consumer has a fingerprinted review in
`tools/compatibility/interactions.json`: supported with test references, pending,
unsupported, external service, or general transport. A changed source file,
removed consumer, parse error or new consumer fails the review gate:

```sh
.venv/bin/python -m tools.compatibility interactions \
  --zotero-source .compatibility/zotero-10.0.5 --check \
  --output .compatibility/interactions.json --markdown .compatibility/interactions.md
```

The initial inventory identifies 109 transport call sites in 88 consumers across
324 source files, with no parse errors. A review records scope, not a passing run.
Expressions retain unresolved dynamic URLs and request options for inspection;
this is not whole-program call-graph analysis. Runtime acceptance traces record
methods, paths, protocol query selectors, header names, response codes and library
versions. Login/storage tokens in paths and credential header values are omitted.
Source replay and actual desktop evidence remain separate.

Library sync is the supported scope. Zotero speech synthesis/credits, legacy
password-to-key creation and legacy `removestoragefiles` are explicitly unsupported,
alongside retractions. WebDAV, publisher downloads, metadata recognition and
repository updates target separate services. Their exclusion is recorded rather
than allowing absence from the scan to imply coverage.

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

The real desktop CI job runs nightly and on manual dispatch. Its official Linux
archive, SHA-256 and version are pinned in `tools/compatibility/desktop.toml`.
The 10.0.5 archive was downloaded through Zotero's official download endpoint
and its application metadata inspected on 2026-10-02. CI checks the archive hash
and running version, runs under Xvfb, and uploads snapshots, logs and desktop
databases even on failure. A successful download is not a successful acceptance
run; the test matrix below records runs separately. The GitHub jobs themselves
have not been executed locally.

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
the desktop log on failure. The verified Zotero 10.0.5 binary and the Node
replay source both use the 10.0.5 release; archive and source hashes are
independent pins.


```sh
uv run python -m tools.compatibility acceptance \
  --desktop-executable /path/to/Zotero_linux-x86_64/zotero --desktop-version 10.0.5 \
  --xvfb --schema-corpus --state-dir .compatibility/desktop-10.0.5
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

The 15-phase baseline passed again with Zotero 10.0.5: parent/note/file download,
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

The conflict scenario also covers an offline edit against a remote deletion.
Zotero 10.0.5's
local choice for the deletion conflict retains the old object version, so the
server's correct 404 triggers full sync and a repeated prompt. Cancelling that
prompt must preserve the pending edit. Choosing local on the next sync lets
full sync reset its version and recreate it; a second edit/delete race chooses
the remote deletion. Both outcomes must settle both desktops.
`--scenario filing` runs
concurrent tag and collection membership additions in a fresh pair of profiles;
both desktops' additions must survive without a conflict dialog.

Each desktop has its own temporary directory and waits for schema/bundled-file
initialization before running operations. This avoids shared translator staging
files and shutdown racing unfinished startup work.

Use `--scenario baseline` or `--scenario conflicts` to run one scenario; repeat
the flag to select several. The default runs every implemented scenario, each
with its own profiles and server under the new state directory. The top-level
`acceptance.json` records scenario results and each subdirectory retains its
phase snapshots and desktop logs.
The optional desktop CI job runs a matrix with one scenario per job against
PostgreSQL 18, so a longer scenario cannot consume another's timeout. Artifacts
have the scenario's name and include the generated database name for diagnosis.

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
detects every timestamp collision. Exactly equal displayed dates exposed a
Zotero 10.0.1 bug: choosing Remote can keep and upload the local bytes.
`Zotero.Sync.Storage.Local.resolveConflicts` identifies the selected side by its
date instead of a side identifier, so either choice matches the local side.
This was reproduced with 10.0.1; the equal-date failure has not been rerun
with 10.0.5. The passing 10.0.5 scenario uses distinct displayed dates to
verify both working choices.
A multi-file HTML snapshot also checks that ZIP transfer restores its HTML
and CSS on disk.

Acceptance phase snapshots also record collections, saved searches, pending
object uploads and group permissions. `AcceptanceRun` compares persisted objects
on both desktops with server responses, normalizing omitted empty/default
properties, collection membership order and scalar/list relation shapes. It
retains keys and checks that both desktops hold positive object versions at
least as high as the server. The original engine deliberately records the
batch watermark on unchanged objects, so a desktop version can exceed that
object's server version. All server pages are read, including beyond 100 objects.
Creator and saved-search condition order remain significant. Matching item titles alone cannot
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
server remains running. Server-process crashes and interrupted uploads are
covered by separate scenarios below.

`--scenario credentials` starts and polls a login session through the original
desktop runner helpers. The disposable server approves it through the same
service the administrator's CLI uses; this is not browser sign-in UI coverage.
After revocation through the original API client, the next sync must report the
specific invalid-key error and retain an offline edit. Relinking must upload
that work to both desktops. Switching B to a second account opens the real
account-mismatch confirmation; Cancel must retain the original owner and data
and leave the second account's library empty. Login handoffs live outside the
uploaded phase artifacts, and phase snapshots contain no issued API key.

Streaming scenarios subscribe over a real WebSocket, make a live write and feed
the greeting, subscription changes and notification into the original `_connect`
message handler. They check sync scheduling, already-current and skipped libraries,
and reconnect delays. The replay supplies a socket facade and virtual clock;
actual desktop reconnect timing and UI scheduling are not exercised.


## Additional desktop scenarios

Each scenario uses two actual 10.0.5 profiles, original desktop operations,
real HTTP, persistent databases and files. Unexpected sync errors fail the run.
The final settled sync checks convergence and an unchanged server watermark.

| Scenario | Assertions |
|---|---|
| `fulltext` | Index an isolated HTML snapshot; upload and download the index; search ASCII, Unicode and CJK terms in B without downloading the attachment; preserve the index across restart. |
| `read-races` | Hold actual settings, top-version, object-batch and deletion responses; edit remotely while B has pending local work; verify download-cycle restart, unseen edits and pending uploads. |
| `settings` | Concurrent tag-color edits and ordering; original settings conflict policy; deletion followed by recreation while B is offline; persisted values and the tag-color cache. |
| `partial-failures` | A mixed group upload succeeds for one object and refuses owner-created parent and child edits with exactly two 403 errors; pending work survives and uploads after permission is restored. |
| `graphs` | Merge duplicate parents and retain children and relations; publish with CC0 and withdraw; copy notes and attachment bytes into a group; repeat the original copy without duplicates. |
| `http-policy` | Induce a real server 429; let the original desktop HTTP policy retry; upload once and converge without continued version changes. |
| `server-writes` | Make collection, filing, tag and trash changes through the browser's authenticated HTTP routes; execute the real retention sweep; observe changes and deletion logs in both desktops. |
| `resync` | Discard pending edits through the original reset helper; replace the server from a desktop; restore an older server archive, lift its watermark and recover from the surviving authoritative desktop. |
| `file-lifecycle` | Rename Unicode filenames; reuse a stored digest and delete one reference; recover a missing local file; refuse a stale download redirect with 404, observe the expected storage failure, then recover current bytes and hashes. |
| `upload-interruption` | Kill the desktop process group while the server has consumed only part of a large incompressible upload; assert no premature registration; restart and compare complete bytes and settled storage states. |
| `server-crash` | SIGKILL a separate serving process after an item commit but before its response; kill the waiting desktop, restart the server on the same database and URL, and recover without duplicate objects or versions. |

HTTP barriers preserve the actual request and response bodies. Upload barriers
require a first chunk with more bytes still expected. Killing only Zotero's
shell launcher leaves its child running, so interruption and timeout handling
terminate the whole isolated process group. A regression test proves the child
stops. Server-crash controls use files outside the HTTP API; worker logs and
barrier traces are preserved.

Barriers can also inject one-shot `status` or `disconnect` failures at the
`before`, `response`, `download` or `upload` boundary. Status injection is confined
to request/response boundaries and error codes. Before-request failures execute
no application write; response failures happen after the application has run.
Partial download failures send a real incomplete HTTP body; upload interruptions
deliver a disconnect after the first portion has been consumed. A subsequent
request runs intact. Socket tests distinguish an uncommitted write from a lost
commit response and verify retry recovery without duplicate objects or versions.
These faults live only in the disposable compatibility harness, not the API.

The storage-error allowance in `file-lifecycle` requires exactly one original
`Zotero.Sync.Storage.defaultError` and a real stale-token 404. Other errors still
fail. Browser writes use real sessions and CSRF tokens, but do not exercise the
browser sign-in UI. Archive recovery follows the documented surviving-client
procedure; it does not claim that raising a watermark rewinds synced desktops
to an older archive.

The inventory keeps separate gaps for graph deletion/reparenting during reads,
rejection of a newly created parent and its dependent child, generic HTTP 5xx
retry/cancellation, simultaneous different ZIP archives under one file digest,
and automatic rewind after restoring an older backup. Reader rendering,
credential expiry/scoping and actual streaming reconnect timing remain uncovered.

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

## Successfully tested matrix

<!-- desktop-matrix -->

Zotero 10.0.5 Linux x86-64; actual desktop profiles.

| Scenario | SQLite | PostgreSQL |
|---|---|---|
| `baseline` | Not run | Passed (15 phases) |
| `conflicts` | Not run | Passed (21 phases) |
| `filing` | Not run | Passed (7 phases) |
| `groups` | Not run | Passed (19 phases) |
| `files` | Not run | Passed (20 phases) |
| `relationships` | Not run | Passed (6 phases) |
| `recovery` | Passed (16 phases) | Passed (16 phases) |
| `credentials` | Not run | Passed (12 phases) |
| `fulltext` | Passed (9 phases) | Passed (9 phases) |
| `read-races` | Passed (24 phases) | Passed (24 phases) |
| `settings` | Passed (11 phases) | Passed (11 phases) |
| `partial-failures` | Passed (10 phases) | Passed (10 phases) |
| `graphs` | Passed (17 phases) | Passed (17 phases) |
| `http-policy` | Passed (7 phases) | Passed (7 phases) |
| `server-writes` | Passed (8 phases) | Passed (8 phases) |
| `resync` | Passed (13 phases) | Passed (13 phases) |
| `file-lifecycle` | Passed (16 phases) | Passed (16 phases) |
| `upload-interruption` | Passed (8 phases) | Passed (8 phases) |
| `server-crash` | Passed (7 phases) | Passed (7 phases) |

<!-- /desktop-matrix -->

Results above are local executions with the pinned Linux x86-64 Zotero 10.0.5
archive on 2026-10-02. PostgreSQL uses the existing 18.4 container, with a fresh
database per scenario. **Not run** means there is no successful result recorded
for that combination; executable inventory entries and scheduled CI jobs do
not count as passes. A successful scenario in a run that later failed is
reported independently.

The machine-readable evidence summary is
[`compatibility-10.0.5.json`](assets/compatibility-10.0.5.json). It records
phase counts and SHA-256 hashes of each report and its phase snapshots. Full
reports, profiles, files and failed attempts remain in ignored local run
directories. Regenerate a matrix from retained reports with:

```sh
uv run python -m tools.compatibility matrix --desktop-version 10.0.5 \
  --report .compatibility/desktop-10.0.5/acceptance.json \
  --report .compatibility/desktop-10.0.5-postgres/acceptance.json \
  --output .compatibility/results.json --markdown .compatibility/matrix.md
```

The command verifies scenario completion, nonempty phases, snapshot existence,
the requested desktop version and recorded database backend. It rejects missing
or mismatched evidence. Interrupted phases retain their process exit status;
completed phases identify their running binary. Summary hashes are evidence
identifiers, not signatures or a certification of the whole desktop surface.

The matrix records 31 successful database/scenario combinations and 392
actual desktop phases: all eight previous and all eleven new scenarios passed
on PostgreSQL; the eleven new scenarios and desktop recovery also passed on
SQLite. The baseline includes all 40 schema types. The complete compatibility
suite passed 172 tests with no skips using the pinned 10.0.5 sources and Node
26.3.0 (CI uses Node 24). All seven mutation canaries passed intact and were
detected by assertion, and the generated seed-14 sequence passed again.

The setting regressions and architecture checks passed 250 tests. Removing the
setting fix made both recreation regressions fail before it was restored.
Formatting, lint, types and the strict docs build passed. The full ordinary
backend suite was not rerun. The PHP dataserver, browser sign-in UI and the
remaining declared desktop gaps were not executed.
