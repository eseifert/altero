# Why altero exists

altero exists for people and organizations that want to run the **Zotero synchronization service itself** on infrastructure they control.

It is not intended to replace Zotero for most users, and it is not a new Zotero client. The goal is narrower: make an unmodified Zotero Desktop application synchronize against a self-hosted server.

## The core requirement

Everything depends on compatibility with the normal desktop client.

A useful self-hosted server must let Zotero Desktop synchronize without patches, custom builds or a separate workflow. That is why altero reproduces upstream behavior even when the behavior is surprising. Where protocol purity and client compatibility conflict, compatibility wins.

The practical test is stronger than “the API endpoints exist”: two real desktop clients should be able to exchange changes through altero without divergence or manual repair.

## What self-hosting changes

### The whole library can stay on infrastructure you choose

WebDAV can place personal-library attachment files on storage you control. It does not move Zotero's metadata synchronization service or group-library file synchronization there.

altero is aimed at users who want the library data, notes, annotations, group metadata, sync history and attachments on their own infrastructure.

That can matter for research groups, institutions, companies and individuals with data-location, privacy or operational requirements.

### The service can fit into a small operational footprint

A basic altero deployment is one application, one database and one attachment directory.

- SQLite can be enough for a small personal installation.
- PostgreSQL is the appropriate choice for concurrent users.
- There is no required search cluster, cache, queue or object-storage service.

That makes the service easier to understand, back up and operate than a larger distributed stack.

### Administration can happen in the browser

Most routine account and group administration is available through the web interface: account settings, API keys, groups, invitations, retention settings, server status and account lifecycle operations.

An **instance administrator** can manage the installation without automatically gaining access to other users' library contents. The role is intentionally about operating the instance, not reading everybody's data.

### Institutional identity can be used for browser sign-in

altero supports OpenID Connect and SAML 2.0 for browser authentication.

The Zotero API still uses API keys. A desktop client receives a key after the user signs in through the browser, so institutional sign-in does not require changing the synchronization protocol.

### Self-hosting makes additional server-side features possible

altero also explores features that are useful in a self-hosted environment, including:

- per-member group restrictions beyond Zotero's normal group-wide policy;
- group activity and notifications;
- configurable retention;
- server-side tag rename;
- links that share one collection without exposing a whole library;
- storage reporting that distinguishes physical disk use from library-accounted use; and
- moving a personal library from zotero.org while preserving keys and versions.

These are secondary to reliable synchronization. A useful feature that breaks a normal Zotero client is still a regression.

## What altero does not try to do

- **Replace zotero.org for everybody.** Hosted Zotero sync is convenient and supports Zotero's development.
- **Fork Zotero Desktop.** If altero requires a patched desktop client, the main compatibility goal has failed.
- **Ship patched mobile apps.** The official mobile clients do not expose an alternate API host at runtime.
- **Change the API simply because a different design would be cleaner.** Compatibility comes first at the protocol boundary.

## What success looks like

1. Two unmodified Zotero Desktop clients can synchronize the same real library through altero without divergence.
2. Attachments, full text and group libraries behave as the desktop client expects.
3. A new instance can be installed, upgraded and backed up from documented procedures.
4. A library can be exported and restored to another compatible instance without losing the versions clients already know.
5. A user can leave an instance without being trapped there.

## Current state

The implementation already covers a substantial part of the Zotero v3 API and desktop synchronization behavior. The test suite exercises real HTTP exchanges and many client-derived edge cases, but the project should still be treated as pre-stable software.

The most important remaining evidence is broad real-world testing across operating systems, Zotero releases, databases and deployment environments.

See:

- [What works](status.md) for the feature-level status;
- [Compatibility notes](compatibility.md) for protocol behavior and deliberate differences; and
- [Syncing two desktop clients](testing-two-clients.md) for the strongest manual end-to-end test.
