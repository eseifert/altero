# Why altero exists

Zotero publishes its Web API and releases its data server under the AGPL, but
the released server is the one Zotero runs: a PHP application assembled for a
particular production environment. Source availability is of little practical
use when running it means reconstructing that environment and understanding
several interconnected services. So in practice, using Zotero means storing
libraries, notes, annotations, group metadata and sync history on infrastructure
one does not operate.

altero exists to close that gap: a data server that an individual or an
institution can actually run, that ordinary Zotero clients treat as their
server.

This is not opposition to zotero.org. Hosting funds Zotero's development and is
the right choice for most users. The published API and the AGPL licence of the
reference implementation are what make a compatible server legitimate rather
than adversarial. What a second implementation adds is a credible exit and the
option of keeping data in-house. Legitimate is not the same as supported, and
Zotero has been consistent that this is not supported; the precondition below
says what that costs.

## The precondition everything else rests on

Every benefit below is worth nothing unless unmodified clients sync against
altero normally. That is the project's first and hardest requirement, and it is
why `docs/compatibility.md` copies upstream quirks rather than correcting them.

Where that stands:

- **Desktop: settled.** `extensions.zotero.api.url` in the Config Editor points
  the client at another server. No custom build, no patched binary. altero
  implements the browser-based key approval the client expects and serves that
  page itself; `altero login approve` does the same from the command line where
  the interface has not been built. See `clients.md`.
- **Mobile: closed.** Both mobile clients compile the host in. Android reads
  `BuildConfig.BASE_API_URL`, a `buildConfigField` set to
  `https://api.zotero.org` in `app/build.gradle.kts`, passed to Retrofit in
  `api/module/ZoteroApiModule.kt`; iOS holds it as
  `baseUrlString = "https://api.zotero.org/"` in
  `Controllers/API/ZoteroApiClient.swift`. Neither has a preference, a debug
  screen or any other runtime override — read from both sources on 2026-08-04,
  after installing the Android app and finding nothing in it. Not in the debug
  build either: the `dev` and `internal` product flavours change the app name
  and the signing suffix and leave the host alone. Pointing a phone at altero
  therefore means building a patched client, which is a non-goal below. "Sync
  across desktop and mobile without Zotero's infrastructure" is not a hope any
  more, it is out of reach: the honest scope of this project is the desktop.
- **Asking upstream is not the missing step.** Zotero does not take feature
  requests on GitHub — both mobile repositories say so in `CONTRIBUTING.md` and
  point at the forums — and on the forums self-hosting has been raised since
  2012 and declined every time. The clearest statement is Dan Stillman's, on
  2022-08-08 in <https://forums.zotero.org/discussion/98918>: the dataserver
  "just isn't designed as an installable package, and we don't provide any
  support for running it that way". The reason given is not licensing or
  principle but support — a server Zotero cannot help you with is one they
  would rather you did not run — and that reason applies to a configurable host
  in a mobile client exactly as it does to the server itself. So this is an
  asked and answered question rather than an unasked one, and altero should
  plan around the answer rather than wait for it to change.
- **A standing risk.** The desktop preference is the only door, it is hidden
  and undocumented, and by the above it belongs to a use its maintainers have
  declined to support for over a decade. It can change or disappear in any
  release, there is no second client to fall back on, and nothing in altero can
  prevent that.

## What running your own server would give users

**Control over where research data lives.** Libraries, notes, annotations, group
metadata, sync history and attachments stay on infrastructure the user or the
institution chooses. That matters for unpublished manuscripts, confidential
research, legal and clinical work, sensitive fieldwork, and organisations whose
policies forbid external cloud storage. WebDAV already covers attachments, but
it does not touch metadata sync or groups — which is the larger part of what
leaves the machine.

**A complete private Zotero environment.** Not an API for programs to talk to,
but the ordinary client experience — collections, tags, groups, sync — served
privately. Useful to research groups, laboratories, companies, departments and
families alike. Complete on the desktop, and only there: anybody evaluating
altero for a group should know before they start that the phones stay pointed
at zotero.org, for the reasons above.

**Infrastructure an administrator can hold in their head.** One server process,
one database and one directory of attachments — no caching tier, no search
cluster, no queue workers, no object store to provision before the first
request. SQLite for a single user; PostgreSQL where concurrency matters. That
shape decides the operational cost more than any other choice: a backup is a
database dump and a directory, an upgrade is one migration command, and the
whole thing fits on a small virtual machine or beside the services an
institution already runs. This is the argument for a new implementation, and it
is about what has to be operated, not what it is written in.

**Administration without shell access.** Anybody who administers a library
should not need a login on the server, and now does not. The interface covers a
person administering themselves — password, email address, an authenticator
app, the signed-in browsers, their own API keys — approving a Zotero client's
login, which was the operation that most often sent somebody to a shell, and
everything to do with a group: creating one, deciding who may read it, edit it
and upload to it, inviting people who have no account here yet, and handing it
on or deleting it.

It also covers the instance itself. Permissions here are per library, with one
exception: an **instance administrator**, which is the account that claims the
instance and can hand the role on from the browser or the shell. It is
deliberately the narrowest thing that will do — it reports what the server is
running and what each library costs on disk, sets how long the trash and the
rest are kept, and makes, suspends and removes accounts. It grants no access to
anybody's library: an administrator counts and measures, and cannot read a
title, a note or a file they were not already entitled to.

What is left on the command line is what belongs there: the first account on a
fresh database, an instance whose administrator has left, and the disaster
recovery in `administration.md`. That is the difference between a server a
librarian or a research-group lead can run and one that needs a systems
administrator.

The interface is not strictly administrative: it reads a library too —
collections, tags, search, an item with its attachments, a citation — and
writes part of one. The line that matters is enforced rather than promised: the
v3 API is reachable by API key and by nothing else, a session cookie is refused
there, and `tests/test_web_routes.py` fails in both directions if that ever
stops being true. What the interface writes goes through the same services and
the same version preconditions as a client's write, not around them.

**Institutional independence.** A university could run Zotero sync as internal
infrastructure the way it runs GitLab, Nextcloud or Matrix — with institutional
accounts, internal groups, retention rules, local backups, regional storage and
continued access when staff leave. Retention rules and the account lifecycle
that deprovisioning needs are built; institutional identity is not. This has been raised on the Zotero forums as
the blocker for organisations that currently reject Zotero outright.

**Plurality of operators.** A personal instance, a departmental server, a
national academic service, a privacy-focused host, a lightweight server for a
small group, an installation that is offline most of the time. Compatibility
also makes managed hosting possible for users who do not want to administer
anything. The gain is that no single operator's pricing, storage policy, account
system or availability is load-bearing.

**Server behaviour that stays inspectable.** altero is AGPL for the same reason
the dataserver is: a provider cannot take it, make significant private changes,
run it as a hosted service and withhold those changes from the people using it.
That keeps authentication, authorization and data handling auditable and
security fixes public. It does not by itself guarantee privacy, security,
maintenance, or that anyone publishes their deployment configuration.

**Room for capabilities the hosted service does not prioritise.** Four are
served. Zotero's own streaming API, so a client pointed at it hears about a
change rather than waiting to ask. Local full-text search, answered by the
database the server already has rather than by the search cluster the
operational shape here rules out. Event notifications: a member of a group
library can ask to hear when it changes, and does, once the library has been
quiet long enough that one sync is one message. And out of the same record, the
activity log upstream has wanted since 2019 and never built — who changed what
in a group and when, readable by every member.

Retention is a fifth: how long the trash is kept, and the record behind the
notifications, are the operator's to set here rather than fixed at thirty days.

Room rather than code: institutional identity integration, more flexible group
policies, storage quotas, backup rules, and integration with repositories and
research-information systems. All of this is secondary: compatibility and
dependable sync come first, and a feature that breaks a client is a regression
however useful it is on its own.

**Portability and disaster recovery as first-class operations.** Exporting a
whole account or group, restoring it elsewhere, replicating to a standby,
verifying backups, migrating between compatible providers. This is what turns
self-hosting from a one-way technical experiment into something an institution
can responsibly depend on.

## Non-goals

- Replacing zotero.org, or competing with it on convenience.
- Forking or patching the Zotero clients. If a change to a client is required,
  the approach is wrong. This is the expensive one, because a patched build is
  the only way a phone reaches another server, so holding to it is what puts
  mobile out of reach above. It holds anyway: a fork would have to be rebuilt
  and redistributed for every Zotero release, outside the app stores, and
  somebody who installed it would be trusting this project with their library
  and not merely with their server. That is a much larger thing to ask, and it
  is the opposite of a credible exit.
- Extending the API where compatibility and a better design conflict.
  Compatibility wins.

## What would count as success

1. A real library syncs in both directions between two unmodified desktop
   clients through altero, with no divergence and no manual repair.
2. Attachments, full-text and groups behave the same way against altero as
   against api.zotero.org.
3. A new instance is installed, upgraded and backed up from documented steps.
4. A library can be exported from altero and restored to another instance.
5. A user who wants to leave can move their data out.

## Status of the claims above

**Point 1 is not evidenced by the thing it describes.**
`tests/test_sync_cycle.py` drives a real server over a real socket with the
request sequence, headers and encodings taken from the client's debug log, and
checks that a second client downloads what the first uploaded. No real library
has been synced between two installed clients and then watched for divergence,
which is a stronger claim than a replay can make.

**Point 2 is reached as far as the test suite can show**; `status.md` has the
feature-by-feature list. One mechanism differs on purpose: upstream searches
attachment text through Elasticsearch and altero through the database it
already has, which has consequences — see the quick-search section of
[compatibility.md](compatibility.md).

**Points 3, 4 and 5 are reached.** A container image and a compose file install
and upgrade an instance, with `GET /health` reporting the migration revision it
is stamped with; `altero library export` and `import` move a whole library
between instances, versions included, which is also what lets a user take their
data elsewhere. Point 4 is sharper than it reads above: a restore that
renumbers versions locks out every client that had synced with the original, in
both directions, so exactness is the requirement rather than completeness.

Intentions rather than properties of the current code: object storage, storage
quotas, federation, replication to a standby, and automatic backup
verification. altero stores attachments on a local filesystem and is configured
by a single file.

**Institutional single sign-on is built**, and it is worth saying exactly what
that means, because it is the thing an institution asks about first. The
browser signs in through an OpenID Connect or SAML 2.0 provider; the API
authenticates with API keys and nothing else, and the two are kept apart on
purpose. A desktop client therefore still holds a key, issued from a signed-in
browser, exactly as before. Single sign-on reaches who may open the interface,
not what the sync protocol accepts — that boundary is the reason this was
possible to add at all, and pretending otherwise would be the wrong promise.
