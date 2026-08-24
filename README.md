# altero

**Your Zotero library. Your server.**

[![CI](https://github.com/eseifert/altero/actions/workflows/ci.yml/badge.svg)](https://github.com/eseifert/altero/actions/workflows/ci.yml)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-006a6a)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-006a6a)](https://www.python.org/)
[![GitHub stars](https://img.shields.io/github/stars/eseifert/altero?style=flat&logo=github)](https://github.com/eseifert/altero/stargazers)

**altero is a self-hosted synchronization server for Zotero.** Point an unmodified Zotero desktop application at it and keep your libraries, groups, notes, annotations, attachments and full text on infrastructure you control.

It speaks the same [Zotero Web API](https://www.zotero.org/support/dev/web_api/v3/start) that the desktop client uses and deliberately reproduces upstream behavior where compatibility matters.

- **Use the normal Zotero desktop app** — no patched client or custom build.
- **Self-host the whole sync service** — not only attachment files.
- **Run a small stack** — one application, one database, one attachment store.
- **Use SQLite or PostgreSQL** — from a personal installation to a shared server.
- **Get a web interface** — libraries, groups, search, account settings, imports, exports and administration.
- **Integrate institutional identity** — OpenID Connect and SAML 2.0 for browser sign-in.
- **Stay in control** — altero is licensed under the GNU AGPL v3 or later.

> [!WARNING]
> **altero is under active development. Do not yet use it as the only home of a library you care about.**
>
> Test it with a separate Zotero profile or a library you can recreate. Synchronization writes client data to the server, and Zotero does not officially support third-party sync servers.

## Why altero?

Zotero is excellent software, and zotero.org is the right sync service for most users. altero exists for people and institutions that need a different deployment model: one where the synchronization service itself runs on infrastructure they operate.

That is different from using WebDAV.

According to [Zotero's synchronization documentation](https://www.zotero.org/support/sync), WebDAV can sync attachment files in a personal library. Library data still uses Zotero's synchronization service, and group-library files cannot use WebDAV.

| | Zotero + WebDAV | altero |
|---|---|---|
| Personal-library attachment files on your storage | Yes | Yes |
| Library metadata on your infrastructure | No | **Yes** |
| Notes and annotations on your infrastructure | No | **Yes** |
| Group-library synchronization on your infrastructure | No | **Yes** |
| Group attachment storage on your infrastructure | No | **Yes** |
| Authentication and account administration under your control | No | **Yes** |
| Unmodified Zotero desktop client | Yes | **Yes** |

altero is therefore not a WebDAV replacement. It is a replacement endpoint for the data and file synchronization services used by the desktop client.

## Who is altero for?

altero may be useful if you are:

- a researcher who wants the library itself, not only PDFs, on a server you control;
- a lab or research group that wants shared Zotero libraries on its own infrastructure;
- a university, library or research organization with data-location or identity-management requirements;
- a self-hoster looking for a practical Zotero synchronization service;
- an administrator who wants OIDC or SAML browser sign-in, retention controls and storage reporting;
- a developer interested in a compact, testable implementation of Zotero's synchronization protocol.

## What works?

The goal is ordinary desktop Zotero synchronization, in both directions.

| Capability | Status |
|---|:---:|
| Zotero desktop synchronization | ✅ |
| Items, collections, tags and saved searches | ✅ |
| Notes and annotations | ✅ |
| Attachments and attachment file sync | ✅ |
| Full-text upload and search | ✅ |
| Group libraries | ✅ |
| My Publications | ✅ |
| Deleted-object synchronization | ✅ |
| Live updates through the streaming API | ✅ |
| Citations and bibliographies | ✅ |
| Zotero export formats | ✅ |
| Browser interface | ✅ |
| OIDC and SAML browser sign-in | ✅ |
| Passkeys and optional second factors | ✅ |
| Importing a personal library from zotero.org | ✅ |
| Zotero iOS and Android apps | ❌ |

The [full implementation status](docs/status.md) documents the API surface feature by feature, including deliberate differences and remaining omissions.

### Desktop yes, mobile no

The desktop application has hidden preferences for the API and streaming server, so it can be pointed at altero without modifying Zotero.

The official iOS and Android applications compile the Zotero API host into the application and provide no runtime setting for replacing it. Supporting them would require patched mobile clients, which is outside altero's scope.

See [Connecting a Zotero client](docs/clients.md) for the details.

## Quick start with Docker

Docker Compose is the easiest way to try altero. It starts PostgreSQL, altero and persistent attachment storage.

```bash
git clone https://github.com/eseifert/altero.git
cd altero

docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml exec altero altero user add <username>
```

The server is published on the loopback interface by default.

For anything beyond local testing, read [Deployment](docs/deployment.md) before exposing it. In particular, put a TLS terminator or reverse proxy in front of altero and set a real PostgreSQL password.

### Point Zotero at altero

In Zotero Desktop, open:

**Settings → Advanced → Config Editor**

Set both preferences:

```text
extensions.zotero.api.url = http://localhost:8000/
extensions.zotero.streaming.url = ws://localhost:8000/stream
```

The trailing slash on `api.url` matters.

> [!IMPORTANT]
> Set the streaming URL as well as the API URL. Zotero resolves the streaming service separately. Leaving it at the built-in default can send the altero API key to zotero.org, where it is not valid.

Restart Zotero, then open:

**Settings → Sync → Link Account**

Zotero opens altero in your browser. Sign in and approve the client. The desktop application receives its API key and synchronization begins normally.

For a detailed walkthrough, including running two test clients at once, see [Connecting a Zotero client](docs/clients.md).

## Run from source

If you prefer not to use Docker, altero requires **Python 3.14 or newer** and [uv](https://docs.astral.sh/uv/).

SQLite is the default database.

```bash
uv sync
cp config.example.py config.py
uv run alembic upgrade head
uv run altero user add <username>
uv run altero
```

The server listens on:

```text
http://127.0.0.1:8000
```

For PostgreSQL outside Docker:

```bash
uv sync --extra postgres
```

See [Deployment](docs/deployment.md) for configuration, health checks, reverse proxies, rate limiting, email and upgrades.

## A deliberately small server

altero is intended to be practical to operate.

A basic installation is:

```text
Zotero Desktop
      │
      │ Zotero Web API + WebSocket
      ▼
   altero
   ├── database
   └── attachments
```

There is no required cache, search cluster, queue or object-storage service.

For a personal installation, SQLite can be enough. For concurrent users, use PostgreSQL. Attachments live in a normal directory, and a backup is fundamentally a database backup plus that directory.

## Web interface

The browser application lives at `/app/`.

It currently supports:

- registration and sign-in;
- account settings and API keys;
- library browsing;
- collections, tags and search;
- item details and citations;
- filing and trashing items;
- group administration;
- My Publications;
- shared collection links;
- tag renaming;
- importing a personal library from zotero.org;
- exporting a library backup;
- administration screens;
- passkeys;
- optional authenticator-app or email second factors;
- OpenID Connect and SAML 2.0 sign-in.

The web interface is not intended to replace Zotero Desktop as a full reference manager. Editing bibliographic fields remains the desktop client's job.

See [The web interface](docs/web-interface.md).

## More than a clone of zotero.org

Compatibility comes first, but running your own server also makes features possible that are difficult or unavailable in the hosted service.

altero includes:

### Institutional sign-in

Use **OpenID Connect** or **SAML 2.0** for browser authentication. Zotero Desktop continues to authenticate with an API key, as the client expects.

### Finer group permissions

A group can go beyond the usual owner/member distinction. Individual members can be restricted to roles such as:

- read only;
- add without removing;
- edit only their own items.

### Share one collection

Create a link to a collection without exposing an entire library or requiring the recipient to have an account.

### Group activity and notifications

Members can see what changed in a group library and can opt into notifications.

### Server-side tag rename

Rename a tag across a library in one operation.

### Configurable retention

Choose how long deleted objects, delivered group activity and unfinished uploads are kept.

### Storage visibility

See what libraries actually consume on disk, including physical versus nominal attachment usage.

### Bring your library with you

altero can copy a personal library from zotero.org while preserving object keys and versions so an already-synchronized desktop client can continue from the same state.

See [Why altero exists](docs/motivation.md) and [Compatibility](docs/compatibility.md) for the design reasoning behind these features.

## Compatibility over purity

altero reimplements a protocol spoken by software that already exists. That changes the engineering priority:

> The right behavior is the behavior the Zotero client expects.

When the published API documentation, the reference data server and observed server behavior disagree, altero favors compatibility with the actual server behavior. Upstream quirks are copied deliberately when clients depend on them, and deliberate departures are documented.

The compatibility work is recorded in:

- [Compatibility](docs/compatibility.md)
- [Implementation status](docs/status.md)
- [Database schema](docs/schema.md)

This is one of the most useful places to contribute: if Zotero behaves differently against altero than it does against zotero.org, that is worth reporting.

## Help test altero

**The project especially needs testers. You do not need to write Python to make a useful contribution.**

A successful test on a configuration nobody has tried before is valuable evidence.

Good ways to help include:

- test synchronization with a recent Zotero desktop release;
- test Windows, macOS or Linux;
- sync the same test library between two desktop installations;
- exercise group libraries with several accounts;
- test attachments and full-text indexing;
- test PostgreSQL deployments;
- test nginx, Caddy, Traefik or another reverse proxy;
- test OIDC or SAML against your identity provider;
- review or improve translations;
- document an installation on NixOS, Unraid, TrueNAS, Kubernetes or another platform;
- review the documentation as a first-time installer;
- report anything that works against zotero.org but not against altero.

If you find a compatibility problem, [open an issue](https://github.com/eseifert/altero/issues/new) and include, where relevant:

- your Zotero version;
- your operating system;
- SQLite or PostgreSQL;
- how altero is deployed;
- the operation you were performing;
- what you expected;
- what happened instead;
- logs or a minimal reproduction that do not contain private library data or API keys.

See [CONTRIBUTING.md](CONTRIBUTING.md) before changing protocol behavior.

## Contributing code

Set up a development checkout with:

```bash
uv sync
uv run pre-commit install
cp config.example.py config.py
uv run alembic upgrade head
uv run pytest
```

Useful commands:

```bash
uv run pytest
uv run ruff format
uv run ruff check --fix
uv run ty check
```

Concurrency tests require PostgreSQL; CI runs them against PostgreSQL rather than silently relying on SQLite's single-writer behavior.

The core architectural rule is that the web framework stays at the API boundary. Domain behavior should remain testable without an HTTP request. See [CONTRIBUTING.md](CONTRIBUTING.md) for the code layout, testing approach and compatibility rules.

## Documentation

The documentation is published at **<https://eseifert.github.io/altero/>** and organized by task; [docs/README.md](docs/README.md) is the same index in the repository, and names a reading path for evaluating, operating, using and developing altero.

| Document | What it covers |
|---|---|
| [getting-started.md](docs/getting-started.md) | A local instance and a test client, from nothing |
| [motivation.md](docs/motivation.md) | Why altero exists and what it is trying to achieve |
| [status.md](docs/status.md) | Implemented and missing API behavior |
| [clients.md](docs/clients.md) | Connecting Zotero Desktop |
| [deployment.md](docs/deployment.md) | Configuration, deployment and upgrades |
| [administration.md](docs/administration.md) | Accounts, keys, groups and libraries |
| [web-interface.md](docs/web-interface.md) | Browser application, over the pages in [docs/web/](docs/web/) |
| [compatibility.md](docs/compatibility.md) | Upstream quirks and deliberate differences |
| [schema.md](docs/schema.md) | Database design |
| [email.md](docs/email.md) | Outgoing email configuration |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development and contribution guidelines |

## Project status

altero already implements a substantial part of the Zotero v3 API and the synchronization behavior needed by the desktop client, but it should still be treated as **pre-stable software**.

The immediate goal is not to maximize feature count. It is to build confidence that real Zotero desktop installations can synchronize reliably across different operating systems, databases and deployment environments.

If altero solves a problem you have, the most helpful things you can do right now are:

1. **try it with a test library;**
2. **report what works and what does not;**
3. **share your deployment experience;**
4. **help another user when you can;**
5. **star the repository if you want more people to discover it.**

## Relationship to Zotero

altero is an independent project. It is not an official Zotero server distribution and is not supported by the Zotero project.

It depends on the openness of the Zotero ecosystem: the published Web API, the open-source desktop client and the [AGPL-licensed Zotero data server](https://github.com/zotero/dataserver) make it possible to study and reproduce the protocol.

This project does not argue that everybody should stop using zotero.org. Hosted Zotero synchronization is convenient and helps fund Zotero's development. altero provides another option for users and institutions that need to operate their own synchronization infrastructure.

## License

altero is free software licensed under the [GNU Affero General Public License v3 or later](LICENSE).
