# altero

**Your Zotero library. Your server.**

**Release candidate: 1.0.0-rc.1.** Feature work is frozen for 1.0.0;
remaining changes are fixes, documentation and translations. See the
[release notes](CHANGELOG.md) and [validation record](docs/release-history.md#release-candidate-1-validation).

[![CI](https://github.com/eseifert/altero/actions/workflows/ci.yml/badge.svg)](https://github.com/eseifert/altero/actions/workflows/ci.yml)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-006a6a)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-006a6a)](https://www.python.org/)
[![GitHub stars](https://img.shields.io/github/stars/eseifert/altero?style=flat&logo=github)](https://github.com/eseifert/altero/stargazers)
[![Documentation](https://img.shields.io/badge/docs-altero.run-006a6a)](https://altero.run/)

altero is a self-hosted synchronization server for Zotero. Use the normal
Zotero Desktop application to keep personal and group libraries on infrastructure
you control. A browser interface lets you manage references, notes, attachments,
collections and accounts alongside it.

- Synchronize library data and files, including notes and annotations.
- Use SQLite for a small installation or PostgreSQL for concurrent users.
- Share collections by link and manage group membership and permissions.
- Set up institutional sign-in and limited access for other applications.
- Offer verified-email account requests with administrator approval, domain restrictions and durable abuse limits.
- Run one application, one database and one attachment directory.

> [!WARNING]
> This is the first release candidate for 1.0.0, ready for final testing before
> the stable release. Keep current backups of your libraries. Back up the server
> database and attachment storage together before upgrading.

## Try it locally

With Docker and Docker Compose installed:

```sh
mkdir altero && cd altero
curl -fsSLO https://raw.githubusercontent.com/eseifert/altero/master/docker/compose.yaml
docker compose up -d
```

Open <http://localhost:8000/app/> and register the first account. That account
administers the instance. Claim it before exposing a fresh instance publicly.
The default image tag is `latest`, including prereleases.

> [!IMPORTANT]
> Set the streaming URL too. Leaving it unchanged can send your altero API key to zotero.org. A profile that has synced before also needs [special handling](https://altero.run/latest/clients/#a-profile-that-has-synced-before).

In a test Zotero Desktop profile, open **Settings → Advanced → Config Editor**
and set both preferences:

```text
extensions.zotero.api.url = http://localhost:8000/
extensions.zotero.streaming.url = ws://localhost:8000/stream
```

Keep the API URL's trailing slash and restart Zotero. Then open
**Settings → Sync → Link Account**, sign in through the browser and approve.

This setup is local to your computer. Follow [Deployment](https://altero.run/latest/deployment/)
before making it available to other people. That guide also covers source
installation, image pinning, HTTPS, upgrades and backups.

## Is it right for you?

altero hosts the synchronization service itself. WebDAV hosts only personal
attachment files while library data still goes through zotero.org. See
[Why altero exists](https://altero.run/latest/motivation/) for the tradeoffs.

The desktop application works without patches. Official mobile apps do not
offer a server setting and need a separate build; altero does not distribute
one. See [client setup](https://altero.run/latest/clients/#mobile-apps).

The browser covers everyday reference management. Use Zotero Desktop for offline
access, PDF annotation and other reader workflows. [What works](https://altero.run/latest/status/)
describes features, known limits and links to recorded compatibility checks.

## Documentation

Read the full documentation at **<https://altero.run/>**, or start here:

| Goal | Guide |
| --- | --- |
| Install and connect Zotero | [Getting started](https://altero.run/latest/getting-started/) |
| Use altero in a browser | [Web interface](https://altero.run/latest/web-interface/) |
| Run and maintain a server | [Deployment](https://altero.run/latest/deployment/) |
| Manage accounts and policies | [Administration](https://altero.run/latest/administration/) |
| Find a setting | [Configuration](https://altero.run/latest/configuration/) |
| Develop or help test | [Contributing](https://altero.run/latest/#for-contributors) |

## Help improve altero

Testing another operating system, reviewing these guides or improving a
translation is as useful as writing code. The [contributor guides](https://altero.run/latest/#for-contributors)
explain how to get started.

For a bug report, include what you expected, what happened, steps to reproduce,
and the altero and client versions, operating system and deployment method.
Remove credentials and private library content from logs before
[opening an issue](https://github.com/eseifert/altero/issues/new/choose).

## Relationship to Zotero

altero is independent and is not supported by the Zotero project. It implements
the published Zotero Web API and follows the behavior clients expect, using
the open-source desktop client and [reference server](https://github.com/zotero/dataserver).

Hosted sync at zotero.org remains convenient and helps fund Zotero's development.
altero is another option for people who need to operate their own service.

## License

[GNU Affero General Public License, version 3 or later](LICENSE).
