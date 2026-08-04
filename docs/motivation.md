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
should not need a login on the server. The web interface reaches about half of
that. It covers a person administering themselves — password, email address, an
authenticator app, the signed-in browsers, their own API keys — and approving a
Zotero client's login, which was the operation that most often sent somebody to
a shell. What still needs one is everything concerning somebody else: creating
an account, creating a group, changing who belongs to it. Registration in the
browser opens only while an instance has no users at all, so the second account
is a command-line account. Missing too is the operational view — versions,
storage use, backups — that an operator otherwise has to infer, and with it any
notion of an instance administrator to show it to: permissions today are per
library and stop there. Until those exist, an instance is still something a
systems administrator runs rather than a librarian or a research-group lead.

This goal came with a constraint — that the interface stay strictly
administrative, and that no browsing interface compete with the clients — and
that constraint has been dropped rather than met. The interface reads a library
too: collections, tags, search, an item with its attachments, a citation. What
survives is the part that was load-bearing, and it is enforced rather than
promised: the v3 API is reachable by API key and by nothing else, a session
cookie is refused there, and `tests/test_web_routes.py` fails in both directions
if that ever stops being true. Reading is all the interface does today; editing
is intended, and when it arrives it will go through the same services and the
same version preconditions as a client's write, not around them.

**Institutional independence.** A university could run Zotero sync as internal
infrastructure the way it runs GitLab, Nextcloud or Matrix — with institutional
accounts, internal groups, retention rules, local backups, regional storage and
continued access when staff leave. This has been raised on the Zotero forums as
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

**Room for capabilities the hosted service does not prioritise.** Institutional
identity integration, more flexible group policies, local full-text search,
custom retention and backup rules, event notifications, administrative import
and export, integration with repositories and research-information systems, and
Zotero's own streaming API for clients that want changes pushed rather than
polled. All of this is secondary: compatibility and dependable sync come first,
and a feature that breaks a client is a regression however useful it is on its
own.

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

Points 1 and 2 are what the test suite and `docs/compatibility.md` work
towards, and are partly reached — see the status list in `status.md`.

Point 1 is not yet evidenced by the thing it describes.
`tests/test_sync_cycle.py` drives a real server over a real socket with the
request sequence, headers and encodings taken from the client's debug log, and
checks that a second client downloads what the first uploaded; but no real
library has been synced between two installed clients and then watched for
divergence. That is a stronger claim than a replay can make, and it has not
been made.

Point 2 has two known holes. Creating a group is a command-line operation and
not an API one. And full-text content is stored, versioned and served back, but
never searched: `q` with `qmode=everything` covers an item's own fields, so text
uploaded from an attachment cannot be found through it, and a child note matches
as itself rather than surfacing its parent.

A web interface is no longer among the intentions below; it exists, and what it
does and does not cover is set out above. The following are still stated here as
intentions rather than properties of the current code: object storage,
institutional single sign-on, audit and retention controls, event notifications,
federation, replication to a standby, and automatic backup verification. Today
altero stores attachments on a local filesystem and is configured by a single
file. It authenticates the API with API keys and the browser with a session
cookie, and keeps those two apart on purpose.

Points 3, 4 and 5 have since been reached. A container image and a compose file
install and upgrade an instance, with `GET /health` reporting the migration
revision it is stamped with; `altero library export` and `import` move a whole
library between instances, versions included, which is also what lets a user
take their data elsewhere. Point 4 turned out to be sharper than it reads here:
a restore that renumbers versions locks out every client that had synced with
the original, in both directions, so exactness is the requirement rather than
completeness.
