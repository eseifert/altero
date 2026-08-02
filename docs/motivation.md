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
option of keeping data in-house.

## The precondition everything else rests on

Every benefit below is worth nothing unless unmodified clients sync against
altero normally. That is the project's first and hardest requirement, and it is
why `docs/compatibility.md` copies upstream quirks rather than correcting them.

Where that stands:

- **Desktop: settled.** `extensions.zotero.api.url` in the Config Editor points
  the client at another server. No custom build, no patched binary. altero
  implements the browser-based key approval the client expects, approved from
  the command line (`altero login approve`). See the README.
- **Mobile: unverified.** Whether the iOS and Android clients expose an
  equivalent setting has not been tested. Until it is, "sync across desktop and
  mobile without Zotero's infrastructure" is a hope, not a claim.
- **A standing risk.** The desktop preference is hidden and undocumented. It is
  not a supported integration point and can change or disappear in any release.
  Nothing in altero can prevent that.

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
families alike.

**Infrastructure an administrator can hold in their head.** One server process,
one database and one directory of attachments — no caching tier, no search
cluster, no queue workers, no object store to provision before the first
request. SQLite for a single user; PostgreSQL where concurrency matters. That
shape decides the operational cost more than any other choice: a backup is a
database dump and a directory, an upgrade is one migration command, and the
whole thing fits on a small virtual machine or beside the services an
institution already runs. This is the argument for a new implementation, and it
is about what has to be operated, not what it is written in.

**Administration without shell access.** Today every account, key, group and
login approval is issued from the command line, which means anyone who
administers a library needs a login on the server. A web interface is a goal:
account and key management, group membership, approving a client's login, and
the operational view — versions, storage use, backups — that an operator
otherwise has to infer. It is what makes an instance something a librarian or a
research-group lead can run, rather than only a systems administrator. It stays
strictly an administrative surface: clients remain the way libraries are read
and written, and no browsing interface will compete with them for that.

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
  the approach is wrong.
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
towards, and are partly reached — see the status list in `README.md`. The
following are stated here as intentions, not as properties of the current code:
a web interface, a packaged deployment unit, object storage, institutional
single sign-on, audit and retention controls, event notifications, federation,
and the export, restore and replication operations above. Today altero
authenticates with API keys, is administered entirely from the command line,
stores attachments on a local filesystem, is configured by a single file, and
has no container image.
