# altero documentation

altero lets you synchronize Zotero libraries on a server you control. Use
Zotero Desktop, the browser interface, or both.

> [!WARNING]
> Keep a current backup of important libraries and don’t rely on altero as your only copy yet.

## Find your guide

| You want to… | Start here |
| --- | --- |
| Try altero on your computer | [Getting started](getting-started.md) |
| Connect Zotero to an existing server | [Connecting a Zotero client](clients.md) |
| Work with your library in a browser | [Web interface](web-interface.md) |
| Run, upgrade or back up a server | [Deployment](deployment.md) |
| Manage accounts and server policies | [Administration](administration.md) |
| Look up a setting | [Configuration](configuration.md) |
| Set up email delivery | [Email](email.md) |
| Connect another application | [Connecting other applications](oauth.md) |
| Evaluate features and limits | [What works](status.md) and [Why altero exists](motivation.md) |

## For contributors

Start with the [development guide](https://github.com/eseifert/altero/blob/master/CONTRIBUTING.md).
Use the [compatibility reference](compatibility.md) and [database schema](schema.md)
when changing server behavior. For browser work, see the [design system](design.md)
and [implementation notes](web/implementation.md).

To help test, follow [two-client testing](testing-two-clients.md),
[desktop compatibility checks](client-compatibility.md), or the
[Podman procedure](testing-podman.md). These pages include the scope and limits
of recorded results.

## Terms used in these guides

- **Instance:** one altero installation, including its database and attachment storage.
- **Library:** a personal or group Zotero library.
- **API key:** a credential used by Zotero Desktop to synchronize. Signing into the browser does not replace it.
- **Connected application:** software you have approved to access your account with limited, expiring tokens.
- **Instance administrator:** someone who manages the server and accounts. This role does not automatically grant access to other people's library contents.
