# altero

**Your Zotero library. Your server.**

[![CI](https://github.com/eseifert/altero/actions/workflows/ci.yml/badge.svg)](https://github.com/eseifert/altero/actions/workflows/ci.yml)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-006a6a)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-006a6a)](https://www.python.org/)
[![GitHub stars](https://img.shields.io/github/stars/eseifert/altero?style=flat&logo=github)](https://github.com/eseifert/altero/stargazers)
[![Documentation](https://img.shields.io/badge/docs-eseifert.github.io%2Faltero-006a6a)](https://eseifert.github.io/altero/)

**altero is a self-hosted synchronization server for Zotero.** Point an unmodified Zotero desktop application at it and keep your libraries, groups, notes, annotations, attachments and full text on infrastructure you control.

It speaks the same [Zotero Web API](https://www.zotero.org/support/dev/web_api/v3/start) that the desktop client uses and deliberately reproduces upstream behavior where compatibility matters.

📖 **The documentation is at <https://eseifert.github.io/altero/>** — installation, connecting a client, deployment, administration and the compatibility reference.

- **Use the normal Zotero desktop app** — no patched client or custom build
- **Self-host the whole sync service** — not only attachment files
- **Run a small stack** — one application, one database, one attachment store
- **Use SQLite or PostgreSQL** — from a personal installation to a shared server
- **Get a web interface** — libraries, groups, search, account settings, imports, exports and administration
- **Integrate institutional identity** — OpenID Connect and SAML 2.0 for browser sign-in
- **Connect other applications** — scoped, expiring OAuth 2.0 access instead of handing out an API key
- **Stay in control** — altero is licensed under the GNU AGPL v3 or later

> [!WARNING]
> **altero is under active development. Do not yet use it as the only home of a library you care about.**
>
> Test it with a separate Zotero profile or a library you can recreate. Synchronization writes client data to the server, and Zotero does not officially support third-party sync servers.

## Why altero?

Zotero is excellent software, and zotero.org is the right sync service for most users. altero exists for people and institutions that need a different deployment model: one where the synchronization service itself runs on infrastructure they operate.

That is more than WebDAV offers. According to [Zotero's synchronization documentation](https://www.zotero.org/support/sync), WebDAV carries attachment files for a personal library; library data still goes through Zotero's service, and group libraries cannot use WebDAV at all. altero replaces the data and file synchronization endpoints themselves, for personal and group libraries alike, along with the accounts and authentication behind them.

Nothing else is required to run it: no cache, search cluster, queue or object store. Attachments live in a normal directory, so a backup is a database backup plus that directory.

See [Why altero exists](https://eseifert.github.io/altero/latest/motivation/).

## What works

Ordinary desktop synchronization in both directions: items, collections, tags, saved searches, notes, annotations, attachments and their files, full-text upload and search, group libraries, deleted objects, live updates through the streaming API, citations, bibliographies and Zotero's export formats. On top of that come a browser interface, OIDC and SAML sign-in, an OAuth 2.0 and OpenID Connect authorization server, passkeys and second factors, and importing a personal library from zotero.org.

The official **iOS and Android applications are not supported**. They compile the Zotero API host into the application and offer no runtime setting to replace it, so supporting them would require patched mobile clients. The desktop application has hidden preferences for both the API and the streaming server, so it needs no patching.

The [implementation status](https://eseifert.github.io/altero/latest/status/) documents the API surface feature by feature, including deliberate differences and remaining omissions.

## Quick start with Docker

Docker Compose is the easiest way to try altero. It starts PostgreSQL, altero and persistent attachment storage. The image is published, so this needs no checkout and no build:

```bash
mkdir altero && cd altero
curl -fsSLO https://raw.githubusercontent.com/eseifert/altero/master/docker/compose.yaml

docker compose up -d
docker compose exec altero altero user add <username>
```

The server is published on the loopback interface by default. An idle instance uses around 125 MB of memory; attachments are what grows.

For anything beyond local testing, read [Deployment](https://eseifert.github.io/altero/latest/deployment/) before exposing it. In particular, put a TLS terminator or reverse proxy in front of altero and set a real PostgreSQL password.

To run without Docker you need **Python 3.14 or newer** and [uv](https://docs.astral.sh/uv/); SQLite is the default database. See [Deployment](https://eseifert.github.io/altero/latest/deployment/#from-a-source-checkout).

### Point Zotero at altero

In Zotero Desktop, open **Settings → Advanced → Config Editor** and set both preferences:

```text
extensions.zotero.api.url = http://localhost:8000/
extensions.zotero.streaming.url = ws://localhost:8000/stream
```

The trailing slash on `api.url` matters.

> [!IMPORTANT]
> Set the streaming URL as well as the API URL. Zotero resolves the streaming service separately. Leaving it at the built-in default can send the altero API key to zotero.org, where it is not valid.

Restart Zotero, then open **Settings → Sync → Link Account**. Zotero opens altero in your browser; sign in and approve the client. The desktop application receives its API key and synchronization begins normally.

For the full walkthrough, including running two test clients at once, see [Connecting a Zotero client](https://eseifert.github.io/altero/latest/clients/).

## More than a clone of zotero.org

Compatibility comes first, but running your own server also makes features possible that are difficult or unavailable in the hosted service:

- **[Institutional sign-in](https://eseifert.github.io/altero/latest/administration/#sign-in-providers)** with OpenID Connect or SAML 2.0, while Zotero Desktop keeps authenticating with an API key.
- **[Scoped access for other applications](https://eseifert.github.io/altero/latest/oauth/)**: altero is an OAuth 2.0 and OpenID Connect authorization server, so a third-party application gets an expiring token confined to the libraries and collections the account holder chooses.
- **[Finer group permissions](https://eseifert.github.io/altero/latest/compatibility/#finer-roles-for-one-member)** beyond owner and member: read-only, add without removing, or edit only your own items.
- **[Shared collection links](https://eseifert.github.io/altero/latest/web/sharing/)**, exposing one collection without an entire library or an account for the recipient.
- **[Group activity and notifications](https://eseifert.github.io/altero/latest/web/groups/)**, so members can see what changed and opt in to hearing about it.
- **[Server-side tag rename](https://eseifert.github.io/altero/latest/compatibility/#renaming-a-tag)** across a library in one operation.
- **[Retention and storage reporting](https://eseifert.github.io/altero/latest/administration/#retention)**: how long deleted objects and unfinished uploads are kept, and what libraries actually consume on disk.
- **[Migration from zotero.org](https://eseifert.github.io/altero/latest/web/data-transfer/)** that preserves object keys and versions, so an already-synchronized client continues from the same state.

## Web interface

The browser application at `/app/` covers registration and sign-in, account settings, API keys, connected applications, library browsing, search, item details and citations, groups, My Publications, shared links, imports and exports, and the administration screens. It is translated into twelve languages, held in fifteen catalogs, and takes item types, fields and creator types from Zotero's own schema translations so the two applications read as one vocabulary.

It is not intended to replace Zotero Desktop as a full reference manager: editing bibliographic fields remains the desktop client's job. See [The web interface](https://eseifert.github.io/altero/latest/web-interface/).

## Compatibility over purity

altero reimplements a protocol spoken by software that already exists. That changes the engineering priority:

> The right behavior is the behavior the Zotero client expects.

When the published API documentation, the reference data server and observed server behavior disagree, altero favors compatibility with the actual server behavior. Upstream quirks are copied deliberately when clients depend on them, and deliberate departures are documented in the [compatibility reference](https://eseifert.github.io/altero/latest/compatibility/).

## Help test altero

**The project especially needs testers. You do not need to write Python to make a useful contribution.** A successful test on a configuration nobody has tried before is valuable evidence — a recent Zotero release, another operating system, two desktop installations sharing a library, group libraries with several accounts, PostgreSQL, a reverse proxy, your identity provider, or an installation on a platform nobody has documented yet. Reviewing the documentation as a first-time installer, and improving translations, help just as much.

If something works against zotero.org but not against altero, [open an issue](https://github.com/eseifert/altero/issues/new). Include your Zotero version, operating system, database, how altero is deployed, what you expected, what happened instead, and logs or a reproduction with no private library data or API keys in them.

For code, a development checkout is:

```bash
uv sync
uv run pre-commit install
cp config.example.py config.py
uv run alembic upgrade head
uv run pytest
```

The core architectural rule is that the web framework stays at the API boundary, so domain behavior remains testable without an HTTP request. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the code layout, the testing approach and the compatibility rules before changing protocol behavior.

## Documentation

The documentation is published at **<https://eseifert.github.io/altero/>**.

| Section                                                                  | What it covers                                                 |
|--------------------------------------------------------------------------|----------------------------------------------------------------|
| [Overview](https://eseifert.github.io/altero/latest/motivation/)         | What altero is and why it exists                               |
| [Get started](https://eseifert.github.io/altero/latest/getting-started/) | Install locally, connect Zotero, first sync                    |
| [Using altero](https://eseifert.github.io/altero/latest/web-interface/)  | Web interface, groups, sharing                                 |
| [Running altero](https://eseifert.github.io/altero/latest/deployment/)   | Deployment, configuration, administration, applications, email |
| [Reference](https://eseifert.github.io/altero/latest/compatibility/)     | Compatibility, implementation status, database schema          |
| [Contributing](CONTRIBUTING.md)                                          | Development and testing                                        |

## Relationship to Zotero

altero is an independent project. It is not an official Zotero server distribution and is not supported by the Zotero project.

It depends on the openness of the Zotero ecosystem: the published Web API, the open-source desktop client and the [AGPL-licensed Zotero data server](https://github.com/zotero/dataserver) make it possible to study and reproduce the protocol.

This project does not argue that everybody should stop using zotero.org. Hosted Zotero synchronization is convenient and helps fund Zotero's development. altero provides another option for users and institutions that need to operate their own synchronization infrastructure.

## License

altero is free software licensed under the [GNU Affero General Public License v3 or later](LICENSE).
