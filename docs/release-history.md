# Release validation history

These are historical records, not results for the current checkout. Keep the
release, client and tool versions attached to each result. For current operation,
use [Deployment](deployment.md); for new release checks, use the
[release checklist](https://github.com/eseifert/altero/blob/master/CONTRIBUTING.md#preparing-a-release).

## Historical upgrade notes

Read the changelog for every release between your installed and target versions.
These notes retain requirements that may matter when upgrading an older instance.

| Starting point or target | Action or effect |
| --- | --- |
| alpha.3 or earlier | Upgrading advances group-library versions once so desktops refresh cached permissions. Personal-library versions are unchanged. |
| beta.2 or earlier | The upgrade builds a full-text index. Allow additional time and disk space. |
| beta.5 or earlier | The first start reads and hashes attachment storage and renames snapshots by their archive digest. Keep free space for the largest snapshot if hard links are unavailable. Downgrading requires restoring storage as well as the database. |
| beta.6 to beta.7 | No database or storage migration was required. |
| beta.8 with SMTP | Set `ALTERO_PUBLIC_URL` before starting; SMTP without a public URL is refused. Account links no longer use request host headers. |
| beta.8 child-item repair | Child notes and attachments incorrectly filed in collections are repaired and receive new versions. Sync every desktop afterwards. Parents and attachment bytes remain intact. |
| rc.1 registration | Existing accounts remain admitted. Approval-based registration is opt-in and requires SMTP/public URL; new-password policy applies without changing existing passwords. See [Accounts](configuration.md#accounts). |
| OIDC issuer saved under beta.7 | If its trailing slash was removed, re-save the exact issuer from provider discovery after upgrading. Existing values cannot be repaired automatically. |

An old password-reset message with an incorrect host is not revoked by upgrading.
After setting the public URL, issue a fresh reset in **Administration → Accounts**
to replace the account's previous token.

## Recorded upgrade matrix

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


## Recorded release checks

### Beta.8 validation

Local release preparation on 2026-11-08 used Python 3.14.10 and Node 24.22.1:

- The full backend run passes 3,718 cases with PostgreSQL, Keycloak and
  SimpleSAMLphp enabled and no skips, using SQLAlchemy 2.0.57. Real HTTP checks
  cover account links with a forged request host and SQLite pool cleanup
  after an SSE disconnect.
- All 27 new session/policy/workflow checks pass, together with the affected
  285-case backend suite and focused linking regressions. Two real Keycloak
  HTTP cases cover OIDC and SAML sign-in, provider proof, API-key creation and
  archive restore. Chromium separately passes SSO-only sign-in, forced OIDC
  reauthentication, key issuance, an authenticated write and archive restore;
  local credential controls are absent in account and administrator screens.
- All 2,265 frontend unit tests pass, together with template types and the
  production build. Note/attachment checks cover returning to a parent beyond
  the first page and changing scope or collection during a pending write.
- The complete 414-case browser matrix passes in one local job: 207 desktop
  and 207 phone cases, with no retries, skips or flaky results. Desktop cases
  have a 30-second budget and phone cases 60 seconds.
- Ruff formatting/lint, Ty and the strict documentation build pass.
- All 333 pinned desktop source-replay checks pass without skips. Verification
  uses separate clean checkouts of the pinned Zotero and dataserver revisions;
  the network-consumer manifest check also passes.
- All fourteen populated upgrade cells pass: beta.1 through beta.7 on SQLite
  and newly created PostgreSQL databases, including bytes, permissions, writes
  and repeat startup, using SQLAlchemy 2.0.57. All end at beta.8 and revision
  `c8f17a2d904e`.
- The wheel/source-archive inventory check passes. Real HTTP from the isolated
  wheel serves `/health` (`1.0.0b8`), `/app/`, its assets and a font, and accepts
  an authenticated item write/read with the wheel ahead of the editable source.
- Beta.8 Podman and arm64 runtime checks remain unverified.

The full two-profile desktop matrix remains the recorded beta.7 run below;
source replay and browser checks are separate evidence.

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

The [recorded desktop matrix](client-compatibility.md#successfully-tested-matrix)
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

The [recorded desktop matrix](client-compatibility.md#successfully-tested-matrix)
has 68 SQLite/PostgreSQL combinations and 794 phases with Zotero 10.0.6 on Linux,
run against the release candidate: all 34 scenarios pass on both databases, each
database in a single run. Remote CI and multi-architecture image publication
must still be checked after pushing.
