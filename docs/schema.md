# Database schema

For contributors changing persistence or synchronization. This reference lists
storage choices that affect API behavior. For migration commands, see the
[development guide](https://github.com/eseifert/altero/blob/master/CONTRIBUTING.md#changing-the-database).

## Adopted from the dataserver

**Tag type belongs to the tag.** `tags` is unique on
`(libraryID, name, type)`, so a name added by hand and the same name added by a
translator are two rows rather than one tag with two links. Tags also carry an eight-character `key`, like every other
syncable object.

**Three timestamps per object.** `dateAdded` and `dateModified` are supplied by
the client and round-trip through the API; `serverDateModified` is set by the
server on every write. Keeping them apart is what makes the `serverDateModified`
sort trustworthy — a client cannot reorder another client's results by
backdating its own `dateModified`. Applied to items, collections, saved searches
and tags via the `Timestamped` mixin in `altero/db.py`.

**Versions start at 1**, not 0, matching `DEFAULT '1'` on every versioned table.

**Collections and searches are trashable.** The dataserver has
`deletedCollections` and `deletedSearches` alongside `deletedItems`, so the
trash is not an item-only concept.

## Deliberate differences

**Pending registration requests are separate from accounts.** The
`registration_requests` table is persistence for the planned verified-email and
administrator-approval workflow. It stores no password or account credential and
creates no user or library. That public workflow is not enabled yet.

Pending rows reserve a canonical username and email address through unique,
nullable columns. Terminal rows release both reservations while retaining the
request's original fields. Constraints require email proof before review,
decision actor/time for approval or rejection, and an account ID for approval.
Actor and account IDs are historical values without foreign keys, so deleting
an account does not erase the recorded decision. They grant no access.

Internal submission defaults to disabled. When explicitly enabled by a trusted
caller, it normalizes the requested name/address, checks existing accounts and
reserves both values atomically. Requests expire at their deadline, releasing
both reservations while keeping history. Activation must recheck availability;
a pending reservation cannot override an account provisioned by an operator.

Verification recording accepts only a live email-pending request and the exact
normalized address its trusted mailbox-proof consumer verified. A replay cannot
refresh the proof or extend the deadline. After the caller authenticates the
applicant, cancellation releases either pending state; terminal history cannot
be reopened. Conditional updates resolve concurrent transitions. Cleanup shares
their transaction so a failed transition does not commit only part of the
operation. These are internal
primitives; applicant sessions and public routes remain to be wired.

An email-pending request can store one outstanding mailbox proof: a unique
SHA-256 token digest, the recipient address and an expiry no later than the
request deadline. The raw link token is never stored. All three proof fields
are present together or absent together; later states cannot retain them. This
internal issuer returns the stored recipient and a fresh random token, retaining
only its SHA-256 digest. Resending replaces the old proof without extending the
request deadline. A link lasts at most 24 hours; equality with either expiry
deadline is already too late.

Proof consumption checks the digest, saved recipient against the current address,
request state and both deadlines in one conditional update. The same update
clears the proof and moves the request to review; concurrent consumers have one
winner. Cancellation, expiry and trusted verification recording also clear any
outstanding token. A failed transaction preserves the earlier link and lifecycle
state together. These helpers send no mail and grant no account or library access;
delivery, resend limits and applicant authorization still need caller integration.

The internal gated-registration policy requires configured SMTP and an absolute
HTTP(S) `public_url`, and refuses SSO-only mode. It retains neither the settings
nor relay credentials. Allowed domains are normalized to lowercase ASCII DNS
names, with duplicates removed. An empty list allows any valid DNS domain;
otherwise matching is exact, and every allowed subdomain must be listed.
Wildcards, trailing dots and Unicode domain spellings are refused; use the
domain's ASCII punycode spelling in both the policy and the address. Existing
account address handling is unchanged. Mailbox verification proves control of
an address, not current institutional membership. This internal policy has no
operator setting or public caller yet, and does not prove the relay is reachable.
Submission and trusted verification recording require this policy explicitly.
Proof issuance and consumption apply its current domain ceiling in their
conditional updates, so a link issued under an older allowlist cannot advance
an ineligible request. Refused issuance leaves the earlier link intact; refused
consumption does not spend it. Restoring eligibility can make a still-live link
usable again. Cancellation and expiry remain available without an admission
policy. Final activation must recheck the policy as well as identity availability.

An authenticated applicant's internal mailbox-change operation also checks the
current policy and refuses addresses held by existing accounts or other pending
requests. A changed address reserves the new mailbox and releases the old one in
the same update, clears outstanding proofs and earlier verification, and returns
either pending state to email-pending. It keeps the original request deadline.
An unchanged normalized address preserves its proof/review state; terminal
requests cannot be reopened. Conflicting reservations and failed commits preserve
the previous mailbox and proof together. The caller must authenticate the
applicant before using this operation; the row ID alone grants no authority.

Internal rejection requires a currently enabled instance administrator, checked
in the database rather than from a cached account object. PostgreSQL locks the
reviewer's row against concurrent demotion, suspension or deletion; the
conditional decision write also includes the authorization predicate. Only a
live review-pending request can become rejected. One write records actor/time,
releases both reservations and preserves mailbox verification/history. Replays
cannot replace the decision. Expiry cleanup shares the same transaction, so a
failed commit preserves both the request and due reservations. Rejection creates
no account or credential. Applicant authentication, CSRF-protected review routes
and account activation are still unwired.

The internal review queue checks current administrator permission on every read
and returns only live review-pending requests, ordered by increasing row ID. Its
cursor is the last returned ID; pages default to 50 and are capped at 200.
Reading neither sweeps expiry nor commits the caller's transaction. Rows may
change between pages; decisions must recheck state and deadlines. The queue
reads applicant metadata only, with no library or credential access. It has no
public endpoint yet.

Applicant access has its own nullable digest/expiry pair on the request, separate
from mailbox proofs and account sessions. Digests are unique; both fields must
be present together, and expiry must follow creation. Applicant access may
outlive the application deadline so a status page can report the outcome. It
does not identify a user or grant library access. Existing requests migrate
without a token. Internal issuance returns a fresh random token once, stores
only its SHA-256 digest and replaces the previous token. It lasts seven days,
independently of the unchanged application deadline. Only a live pending
request can receive one; the trusted caller must already be authorized.

Status lookup returns only the request ID, state and application deadline. It
reports a due pending request as expired without mutating history, and retains
terminal outcomes until token expiry. Cancellation authenticates the token and
checks its expiry, the request state and deadline in one conditional write.
It clears mailbox proofs and reservations, while retaining the applicant token
for status reads. Revocation clears only the credential. Neither operation
creates a user or account session; normal browser and v3 credentials cannot be
obtained from this token. The combined internal submission operation commits
the reservation, initial applicant-token digest and due-reservation cleanup in
one transaction, returning the raw token only after success. Failure rolls back
all three and leaves the identity available for retry. Internal composition
stages these writes without committing; callers must finish or roll back the
transaction. Replacements must authenticate the applicant before wiring public callers.
Delivery to the submitting browser and recovery from a lost response still need
public-flow integration; database atomicity alone cannot guarantee receipt.
The applicant read/cancel/logout routes below use these helpers, but no public
submission or replacement issuer is enabled yet.

`GET /web/registration` reads only the request named by the separate
`altero_applicant` cookie, returning ID/state/deadline with `Cache-Control:
no-store`. Account cookies, API keys and bearer headers cannot authenticate it.
A successful read sets a separate readable `altero_applicant_csrf` cookie,
derived from the applicant credential with a domain-separated HMAC. Unsafe
`POST /web/registration/cancel` and `/logout` require that value in both the
cookie and `X-CSRF-Token`; an attacker-chosen matching pair is insufficient.
Cancellation repeats token/state/deadline checks in its write and returns 409
if the request can no longer be cancelled. Logout revokes applicant access and
clears only its cookies, leaving any account session intact. Future submission
must set the applicant credential HttpOnly, SameSite=Lax and Secure over HTTPS,
with path `/web/registration`; the CSRF cookie uses `/` for the interface to read.
These routes issue no applicant credential, create no application or user, and
send no mail. They do not enable the planned registration workflow.

**The trash is a flag, not a table.** The dataserver records trashed objects in
`deletedItems(itemID, dateDeleted)`; altero uses a `deleted` boolean on the
object. The queries are equivalent and the flag avoids a join on every listing.
The cost is that the deletion time is not kept, which nothing in the v3 API
exposes.

**Creators are not deduplicated.** The dataserver interns creators in a
`creators` table and links them through `itemCreators`, so one person shared by a
thousand items is stored once. altero stores creators inline on the item. This
trades space for simplicity; deduplication can be introduced behind the same
service functions if it ever matters.

**Notes and attachments are not separate tables.** The dataserver keeps
`itemNotes` (with a sanitized copy and an 80-character derived title) and
`itemAttachments`. altero stores both a note's content and an attachment's
storage columns as ordinary field rows in `item_fields`. Those fields are not in
the published schema, so the set each type accepts is declared in
`UNLISTED_FIELDS` in `services/itemwrites.py` rather than derived.

The upside is that one code path stores every field of every item type. The
cost is that nothing at the database level constrains an attachment to have a
`linkMode`, where a dedicated table would.

**Relations belong to objects.** Items and collections each have relation rows
that produce their API `relations` maps. This differs from upstream's general
library-scoped relation table.

**Sort keys are columns on the item.** The dataserver keeps `itemSortFields`
(`sortTitle` truncated to 79 characters, plus `creatorSummary`) in a side table
and joins `itemData` for date sorting. altero keeps `sort_title`, `sort_creator`
and `sort_date` on `items`, untruncated, so every sort is a single-table index
scan.

**No sharding.** `shards`, `shardHosts` and `shardLibraries` have no
counterpart: the dataserver spreads libraries across MySQL servers, and altero
uses one database.

**Files are stored by digest.** Identical registered bytes are stored once at
`<storage>/<first two digest characters>/<digest>`. Upload authorizations live
in `storage_uploads` until registration. Each attachment records its registered
file separately from client-supplied metadata, so a claimed digest does not
confer access to another library's bytes.

Deleting an item does not immediately remove its stored bytes. Administrators
can remove unreferenced and abandoned staging files from Storage, with a grace
period protecting uploads in progress.

**The item type schema is not in the database.** The dataserver stores item
types, fields and their mappings in `master.sql` tables (`itemTypes`, `fields`,
`baseFieldMappings`, …). altero reads them from the vendored `schema.json`
instead, which keeps them in step with the published schema and out of
migrations. Item types and field names are therefore stored as strings rather
than as foreign keys to an ID table.

## Tables with no direct counterpart

`write_tokens` records a `Zotero-Write-Token` for as long as a client might
retry with it, so a repeated request does not create the objects twice. The
dataserver caches these outside the database.

`item_fulltext` holds the text a client extracted from an attachment, matching
the dataserver's table of the same purpose, without the reindexing bookkeeping
that a hosted service needs.

`settings` stores sync setting values as JSON text rather than separate modeled fields.

## Delete log

`syncDeleteLogKeys(libraryID, objectType, key, timestamp, version)` backs
`/deleted?since=`, with `objectType` one of `collection`, `creator`, `item`,
`relation`, `search`, `setting`, `tag` or `tagName`. Its primary key is
`(libraryID, objectType, key)`, so deleting a key that was deleted before
updates the existing row rather than adding a second one. altero mirrors this
shape in `deleted_objects`.

## Concurrency

Writes to one library are serialized by taking a row lock on it before the
version precondition is checked and holding it until commit, so a request is
atomic with respect to its library. `SELECT ... FOR UPDATE` is emitted on
PostgreSQL and dropped on SQLite, which has a single writer anyway. The version
increment itself is computed by the database rather than in Python, so it stays
correct even without the lock.

Write-token and tag get-or-create operations use unique constraints rather
than a separate existence check followed by insertion. This preserves their
correctness independently of library locking.

SQLite is configured with `foreign_keys=ON`, WAL and a busy timeout.
`BEGIN IMMEDIATE` is deliberately not used: it would close the remaining
lock-upgrade hole, but takes the write lock for read-only transactions too, so a
single long read would block every writer. A deployment serving several clients
at once should use PostgreSQL.
