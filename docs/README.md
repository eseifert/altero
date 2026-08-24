# altero documentation

altero is a self-hosted synchronization server for Zotero Desktop.

> [!WARNING]
> altero is under active development. Use a test Zotero profile or a library you can recreate. Do not use it yet as the only copy of a library you care about.

## Start here

| I want to… | Read this |
| --- | --- |
| Try altero locally | [Getting started](getting-started.md) |
| Connect Zotero Desktop | [Connecting a Zotero client](clients.md) |
| Run or upgrade a server | [Deployment](deployment.md) |
| Manage users, groups, retention or sign-in providers | [Administration](administration.md) |
| Configure outgoing email | [Email](email.md) |
| Use the browser interface | [Web interface](web-interface.md) |
| Test synchronization with two real clients | [Two-client testing](testing-two-clients.md) |
| Check whether a feature is implemented | [Implementation status](status.md) |
| Understand why altero exists | [Motivation](motivation.md) |
| Investigate Zotero protocol behavior | [Compatibility reference](compatibility.md) |
| Understand the database | [Database schema](schema.md) |
| Work on the browser design system | [Design system](design.md) |

## Choose your path

### I am evaluating altero

Read these in order:

1. [Why altero exists](motivation.md) — what problem it solves, what it does not try to replace, and the current limits.
2. [Getting started](getting-started.md) — run a local test instance and connect Zotero Desktop.
3. [What works](status.md) — feature status and known omissions.

You do **not** need the compatibility or schema documents to try altero.

### I run an altero server

Start with [Deployment](deployment.md). It covers Docker Compose, source installations, upgrades, health checks, reverse proxies and the main configuration settings.

Then use:

- [Administration](administration.md) for accounts, API keys, groups, retention, library moves and institutional sign-in.
- [Email](email.md) if you want confirmations, invitations, security messages or group digests delivered by mail.
- [Web interface](web-interface.md) for what ordinary users and administrators can do in the browser.

### I use altero but do not administer the server

The [Web interface](web-interface.md) is the main guide. It links to shorter pages for account settings, library browsing, sharing, groups and data transfer.

For Zotero Desktop setup, use [Connecting a Zotero client](clients.md).

### I develop or test altero

Use:

- [Implementation status](status.md) for the supported API surface.
- [Compatibility reference](compatibility.md) for behavior copied from or deliberately different from zotero.org.
- [Two-client testing](testing-two-clients.md) for end-to-end synchronization with real Zotero installations.
- [Database schema](schema.md) for persistence and concurrency rules.
- [Design system](design.md) for browser UI work.

## A few terms used throughout the docs

**Instance**  
One running altero server and its database and attachment storage.

**Library**  
A Zotero personal library or group library.

**Group**  
A shared Zotero library with members and permissions.

**API key**  
The credential Zotero Desktop uses to synchronize with altero. Browser sessions and API keys are separate credentials.

**Instance administrator**  
An account allowed to manage the altero installation itself. This role does not automatically grant access to other users' library contents.
