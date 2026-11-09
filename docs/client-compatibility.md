# Checking desktop compatibility

Run the optional compatibility suite when changing responses or versions that
Zotero Desktop consumes. It feeds altero API responses into original desktop
functions, and inventories source expectations to find contracts worth testing.

Choose the check that matches the change:

| Check | Evidence |
| --- | --- |
| Source discovery | Candidate omissions and network consumers to review |
| Source replay | Original desktop methods consuming altero responses |
| Generated sequences | State invariants across ordered operations |
| Desktop acceptance | Actual profiles, sync engine, dialogs and files |
| Mutations | Whether assertions detect deliberate defects |

The normal Python suite needs neither Node nor a desktop checkout. This optional
toolchain needs Node matching `tools/compatibility/package.json`, its own parser
installation, and the source revision in `tools/compatibility/contracts.toml`.
The installed desktop binary is pinned independently in `desktop.toml`.

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

The `child-demotion` acceptance scenario makes a standalone PDF into a child
and verifies that collection memberships are removed and both profiles settle.
This protects against a desktop foreign-key failure on invalid child membership.

Source selectors identify original JavaScript functions. Adapters provide
HTTP, persistence and file facades while retaining the selected decision logic.
`DesktopAPI` runs the original API client over live HTTP; `DesktopStorage` runs
its file-transfer methods. Subprocess calls remain asynchronous so the server
can answer them.

These facades do not prove generic HTTP retries, desktop disk writes or ZIP
unpacking. Actual desktop acceptance supplies that evidence separately.

Duplicate merging has service, HTTP, browser and desktop checks. They cover
field choices, relations, permissions, rollback, stale reviews, attachment
matching, notes and annotation parents. PDF extraction uses a different parser
from Zotero, so matching arbitrary PDFs is not guaranteed. Extraction failures
are treated conservatively as possible embedded markup. The browser merge
contract is documented in [implementation notes](web/implementation.md#duplicate-merge-endpoint).

Source replay and real desktop scenarios are separate inventory entries; neither
should stand in for the other.

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
  --zotero-source .compatibility/zotero --check \
  --output .compatibility/interactions.json --markdown .compatibility/interactions.md
```

The inventory is syntactic, not a whole-program call graph. Dynamic URLs and
unresolved options stay visible for review. Supported library sync, unsupported
services, external services and general transport each retain their disposition.
Runtime traces omit credential values and login/storage tokens in paths.

An inventory entry records scope, not a successful run.

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

The report compares mapped client field reads with possible server response
shapes and retains source positions, unmapped consumers and parse errors.

| Status | Meaning |
| --- | --- |
| `candidate` | No known emission for a client-read field; reproduce the effect |
| `no-static-gap` | Static fields match; behavior still needs tests |
| `execution-only` | Executable check without static field comparison |
| `unresolved` | Dynamic shape or source prevents comparison |

Presence does not establish correct values or permissions. Zero candidates
therefore does not establish compatibility. Discovery reports findings without
failing; exit 2 indicates unusable prerequisites or runner/output errors.

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

The **Desktop compatibility** workflow verifies pinned sources, replays contracts
and rejects skips. Reports include source discovery, reference evidence,
scenario inventory and test results. Nightly/manual checks also inspect upstream
source with drift allowed and run mutations without changing the supported pin.

Real desktop acceptance runs separately under Xvfb. CI checks the Linux archive
hash and running version from `desktop.toml` and preserves reports, logs and
databases on failure. Scheduled jobs and successful downloads are not passing
acceptance results; use the [recorded matrix](#successfully-tested-matrix).

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

Sequences use a fresh loopback server, database and file store. Existing state
directories are refused. The independent model checks effective create, edit,
file, unfile, trash, restore and delete operations after each step.

Failures shrink on fresh servers while retaining the invariant's object family,
key and field. Invalid or ineffective sequences do not count as reproductions.
Reports preserve original and minimized operations. Exit 1 means an assertion
failure; runner and prerequisite failures use exit 2.

Run and replay a standalone sequence with preserved disposable databases:

```sh
uv run python -m tools.compatibility sequence --zotero-source .compatibility/zotero \
  --seed 14 --steps 30 --state-dir .compatibility/sequence-14 \
  --output .compatibility/sequence-14.json
uv run python -m tools.compatibility sequence --zotero-source .compatibility/zotero \
  --replay .compatibility/sequence-14.json --state-dir .compatibility/replay-14 \
  --output .compatibility/replay-14.json
```

Use `--model protocol --steps 60` for the broader model covering object graphs,
settings, files, full text, deletions, permissions and two offline patch queues:

```sh
uv run python -m tools.compatibility sequence --zotero-source .compatibility/zotero \
  --model protocol --seed 14 --steps 60 --state-dir .compatibility/protocol-14 \
  --output .compatibility/protocol-14.json
```

Replay selects the recorded model automatically. Shrinking rejects orphaned
children, collection cycles, denied writes, stranded work and no-op operations.
The queued-patch policy belongs to this harness, not Zotero's desktop engine.

## Run two real desktop profiles

Acceptance runs two isolated desktop profiles against a disposable server,
using the actual sync engine and file storage. Supply an installed executable
and its exact version; use the archive pin in `desktop.toml` for reproducible CI
comparisons.

```sh
uv run python -m tools.compatibility acceptance \
  --desktop-executable /path/to/zotero --desktop-version <installed-version> \
  --xvfb --schema-corpus --state-dir .compatibility/desktop-run
```

Use a fresh state directory. `--xvfb` requires Xvfb; omit it for an existing
display. Each profile gets its own temporary directory and waits for schema and
bundled-file initialization. The add-on applies operations through original
Zotero APIs without replacing sync or conflict dialogs.

For PostgreSQL, add
`--postgres-url postgresql+asyncpg://altero:altero@localhost:55432/altero`.
The account must be able to create databases. Each scenario creates and retains
a fresh database; its name is saved in `server/database.json` without credentials.
The database named in the URL is not migrated. Without this option, SQLite
state stays in the run directory.

Repeat `--scenario` to select cases; the default runs all implemented scenarios.
The top-level `acceptance.json` and scenario directories retain snapshots and
logs, including on failure.

| Core scenario | Coverage |
| --- | --- |
| `baseline` | Parent/child objects, schema types, attachment bytes, offline edits, trash and deletion |
| `conflicts` | Actual local/remote choices, edit/delete conflicts, cancellation and recovery |
| `filing` | Concurrent tag and collection additions |
| `groups` | Role/policy changes, permission-loss choices, archival, removal and rejoining |
| `files` | Replacement, both file-conflict choices, missing-file recovery and snapshot unpacking |
| `relationships` | Collection moves, reparenting, type changes, searches and annotations |
| `recovery` | Interrupted desktop requests and downloads, restart and concurrent pending work |
| `credentials` | Login helpers, revocation, relinking and account-mismatch cancellation |

The convergence check compares all pages of persisted objects, child graphs,
fields, significant list ordering, pending work and downloaded bytes. Matching
titles alone is insufficient. Desktop item versions may exceed server object
versions because the client stamps a batch watermark. `lastRead` is normalized
numerically; setting values and finished queues must match even where setting
version metadata differs.

File-conflict tests use different displayed modification dates. Equal-date
selection has a [recorded client defect](#recorded-client-behavior) and is not
covered by a passing distinct-date scenario. Missing files are recovered through
the original on-demand download rather than forced storage flags.

Source replay of streaming handlers uses a socket facade and virtual clock.
The `streaming-reconnect` acceptance scenario separately checks actual sockets,
resubscription and notification-driven sync.

## Additional desktop scenarios

Each scenario uses two actual desktop profiles, original desktop operations,
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
| `web-editing` | Edit an item's fields, creators and tags, relate two items, change a type and make an item through the browser's routes; both desktops store exactly that; a desktop edit then makes the browser's stale save fail with 412. |
| `web-undo` | Trash and file a selection through the browser, then undo after both desktops have synced; preserve prior memberships, preexisting trash and child-note HTML/parents; a real desktop edit invalidates a stale undo. |
| `web-copy-undo` | Copy a parent, note and registered file into a group; sync both desktops before undo; keep the copied graph and bytes recoverable through Trash/Restore, and preserve the originals. |
| `web-merge-undo` | Merge two PDFs with embedded notes and an annotation; sync both desktops before undo; restore original metadata, links, memberships, note HTML and parents, trash promoted notes and retain file bytes. |
| `note-corpus` | Store notes as clients wrote them, from TinyMCE-era HTML to schema 10 and a note built from PDF annotations; have the shipped note editor save each unedited; record both for the browser editor's tests, and check the server keeps the desktop's HTML exactly. |
| `web-notes` | Write a standalone and a child note through the browser's routes; both desktops store exactly that HTML; the desktop's editor opens them editable and writes nothing; a desktop edit reaches the browser. |
| `web-files` | Upload a child and a standalone file and attach a web link through the browser's routes; both desktops download the bytes under the browser's name; a rename renames each desktop's copy without fetching it; a replacement brings new bytes; a desktop's replacement makes the browser's stale one fail with 412. |
| `web-merge` | Merge through the browser route; both desktops retain chosen fields, moved notes and links, tags, collections, incoming relations and replacement history; refuse a stale review; restore the duplicate record without reversing the merge. |
| `web-merge-files` | Match PDFs by bytes or extracted text, retain embedded markup, preserve notes and annotation parents, keep both files when needed for safe parent sync, and verify original bytes and settled storage on both desktops. |
| `resync` | Discard pending edits through the original reset helper; replace the server from a desktop; restore an older server archive, lift its watermark and recover from the surviving authoritative desktop. |
| `file-lifecycle` | Rename Unicode filenames; reuse a stored digest and delete one reference; recover a missing local file; refuse a stale download redirect with 404, observe the expected storage failure, then recover current bytes and hashes. |
| `upload-interruption` | Kill the desktop process group while the server has consumed only part of a large incompressible upload; assert no premature registration; restart and compare complete bytes and settled storage states. |
| `server-crash` | SIGKILL a separate serving process after an item commit but before its response; kill the waiting desktop, restart the server on the same database and URL, and recover without duplicate objects or versions. |
| `graph-races` | Reparent a note and delete its former parent while top-version, object-batch and deletion responses are held; preserve unrelated pending work and converge without resurrecting the parent. |
| `credential-limits` | Expire and cancel actual login sessions through original desktop methods; remove a key's personal-library read access while offline work is pending, restore access and upload that work. |
| `transient-errors` | Real 503s before and after a write, a lost commit response, a truncated object read, and user cancellation through the original sync runner; recover without duplicates or extra versions. |
| `streaming-reconnect` | Close the actual WebSocket with 1012, observe the original two-second reconnect delay and resubscription, then send a notification that drives automatic desktop sync without an explicit sync call. |

HTTP barriers hold genuine requests independently. A fault before execution
performs no write; a response fault can lose an already committed answer.
Partial download and upload failures use incomplete transport bodies. Crash
checks restart the same database and URL and compare durable state and retry
preconditions. A consumed file-registration token returns 404 on retry; current
metadata and downloaded bytes establish recovery.

Process interruption terminates the entire isolated desktop process group.
Barrier traces redact credentials. These controls exist only in the disposable
harness. Socket-level durable-write checks remain distinct from desktop acceptance.

Seven further cases cover additional transitions:

| Scenario | Coverage |
| --- | --- |
| `parent-rejection` | Rejected parent and dependent 409, unrelated success, displayed errors and retry |
| `missing-parent` | A synced parent missing on the server is requeued from the child's 409 |
| `child-promotion` | `parentItem: false` makes a child top-level on both desktops |
| `type-change` | Fields and creator roles map to a different item type |
| `reader-rendering` | Actual PDF canvas pixels, changed PNG cache after crop and restart persistence |
| `zipped-digest-race` | Concurrent uploads with equal main-file digests and different ZIPs; archive integrity and unpacked resources |
| `backup-rewind` | A raised watermark does not rewind desktop objects; explicit surviving-client recovery |

Browser-route scenarios use real sessions and CSRF tokens, but do not establish
browser sign-in UI coverage. Automatic rewind remains unsupported. More platforms,
credential combinations, reader formats and failure schedules need separate evidence.

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

These are historical local runs, not results for the current checkout. The
original release-candidate run and later additions are identified below.

<!-- desktop-matrix -->
Zotero 10.0.7 Linux x86-64; actual desktop profiles.

| Scenario | SQLite | PostgreSQL |
|---|---|---|
| `baseline` | Passed (15 phases) | Passed (15 phases) |
| `conflicts` | Passed (21 phases) | Passed (21 phases) |
| `filing` | Passed (7 phases) | Passed (7 phases) |
| `groups` | Passed (19 phases) | Passed (19 phases) |
| `files` | Passed (20 phases) | Passed (20 phases) |
| `relationships` | Passed (6 phases) | Passed (6 phases) |
| `recovery` | Passed (16 phases) | Passed (16 phases) |
| `credentials` | Passed (12 phases) | Passed (12 phases) |
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
| `transient-errors` | Passed (22 phases) | Passed (22 phases) |
| `streaming-reconnect` | Passed (6 phases) | Passed (6 phases) |
| `parent-rejection` | Passed (8 phases) | Passed (8 phases) |
| `missing-parent` | Passed (8 phases) | Passed (8 phases) |
| `child-promotion` | Passed (6 phases) | Passed (6 phases) |
| `type-change` | Passed (6 phases) | Passed (6 phases) |
| `reader-rendering` | Passed (12 phases) | Passed (12 phases) |
| `zipped-digest-race` | Passed (13 phases) | Passed (13 phases) |
| `backup-rewind` | Passed (10 phases) | Passed (10 phases) |
| `graph-races` | Passed (19 phases) | Passed (19 phases) |
| `credential-limits` | Passed (12 phases) | Passed (12 phases) |
| `web-editing` | Passed (7 phases) | Passed (7 phases) |
| `web-undo` | Passed (15 phases) | Passed (15 phases) |
| `web-copy-undo` | Passed (14 phases) | Passed (14 phases) |
| `web-merge-undo` | Passed (11 phases) | Passed (11 phases) |
| `note-corpus` | Passed (5 phases) | Passed (5 phases) |
| `web-notes` | Passed (8 phases) | Passed (8 phases) |
| `web-files` | Passed (11 phases) | Passed (11 phases) |
| `web-merge` | Passed (11 phases) | Passed (11 phases) |
| `web-merge-files` | Passed (9 phases) | Passed (9 phases) |

<!-- /desktop-matrix -->

Results above are local executions with the pinned Linux x86-64 Zotero 10.0.7
archive on Python 3.14.10. The original 36 scenarios ran on each database on 2026-10-30
against the beta.7 release candidate, including the 15-phase schema baseline.
PostgreSQL uses the existing 18.4 container, with a fresh database per scenario.
**Not run** means there is no successful result recorded for that combination;
executable inventory entries and scheduled CI jobs do not count as passes.

The additional `web-undo` scenario passed on both databases on 2026-11-02,
with 15 phases each against the current checkout. Both desktops downloaded
filing and trash changes before undo, then converged on the restored state;
a subsequent desktop edit made an old undo fail with 412. Its separate
[evidence summary](assets/compatibility-web-undo-10.0.7.json) records report and
phase-snapshot hashes.

`web-copy-undo` also passed on both databases on 2026-11-02, with 14 phases
each. Both desktops downloaded a browser-made group copy before undo and
retained its note and registered bytes through Trash/Restore. The original
personal-library records and files remained intact, and settled sync preserved
both libraries' watermarks. Its [evidence summary](assets/compatibility-web-copy-undo-10.0.7.json)
records the reports and phase-snapshot hashes.

`web-merge-undo` passed on both databases on 2026-11-03, with 11 phases each.
Both desktops received a merge of two PDFs with embedded notes and an annotation
before Undo restored the original content, dates added, parent links, tags,
collections and relations. Promoted notes went to Trash, both original PDF files
remained intact, and the next sync preserved the library watermark. The fixture
forces duplicate restoration before its survivor's update, exercising Zotero's
automatic merge-link cleanup and the preservation of relation-only modification
dates. It also verifies clearing the last creator reaches both desktop caches.
The [evidence summary](assets/compatibility-web-merge-undo-10.0.7.json) records
report and phase-snapshot hashes. These are local Linux checks; the scenario is
also included in the scheduled/manual PostgreSQL CI matrix. No hosted run or
non-Linux execution is claimed for this addition.

The machine-readable evidence summary is
[`compatibility-10.0.7.json`](assets/compatibility-10.0.7.json). It records
phase counts and SHA-256 hashes of each report and its phase snapshots. Retained
reports, profiles, files and failed attempts live in ignored local run
directories. Regenerate the matrix from them with:

```sh
uv run python -m tools.compatibility matrix --desktop-version 10.0.7 \
  --report .compatibility/beta7-10.0.7-sqlite-1/acceptance.json \
  --report .compatibility/beta7-10.0.7-pg-1/acceptance.json \
  --output .compatibility/results.json --markdown .compatibility/matrix.md
```

The command verifies scenario completion, nonempty phases, snapshot existence,
the requested desktop version and recorded database backend. It rejects missing
or mismatched evidence. Interrupted phases retain their process exit status;
completed phases identify their running binary. Summary hashes are evidence
identifiers, not signatures or a certification of the whole desktop surface.

The original 2026-10-30 run recorded 72 database/scenario combinations and 838
phases across 36 scenarios. Later undo scenarios are recorded separately above.
The baseline includes all 40 schema types.
The 2026-10-30 source-replay run passed 333 tests with no skips against the
pinned 10.0.7 sources, with Node 24.22.1; its network-consumer review gate had
no stale or unreviewed consumers. Regressions cover the restore request marker
and reconnecting after WebSocket close 4429; both fail against the older source.

The earlier 10.0.6 browser-merge checks also ran with deliberate omissions
after their intact baselines passed. Missing replacement history failed at
`Desktop merge history is missing` after five phases; disabling PDF text
matching failed at `Incorrect surviving PDFs for matching-text` after seven.
Those failed runs and the restored-source hashes are retained locally.

Two harness defects surfaced while moving to 10.0.6 and are fixed: profiles
followed the machine's language, so a German system showed prompts the dialog
rules could not find, and Zotero's automatic update could replace a pinned
binary between phases. Profiles now request English and turn automatic updates
off. The PHP dataserver and browser sign-in UI were not executed. The desktop
evidence is Linux-only; exhaustive credential combinations, reader formats and
failure schedules remain unverified.

## Recorded client behavior

Equal displayed file-conflict dates exposed a client defect: selecting Remote
can keep and upload local bytes. It was reproduced with Zotero 10.0.1, and with
10.0.6 against Zotero Storage on 2026-10-30. The
[upstream report](https://forums.zotero.org/discussion/134528/bug-selecting-remote-in-a-file-conflict-can-upload-the-local-file)
records dialog selection, hashes and a passing different-date control. This
case has not been rerun on 10.0.7; its acceptance run used distinct dates.

PDF parent/note merging also reproduced a Zotero 10.0.6 defect against zotero.org
and offline: a changed note could persist while its parent move was lost.
altero retains both PDFs when that combination would occur; see
[the compatibility decision](compatibility.md#merging-pdfs-with-embedded-notes).
