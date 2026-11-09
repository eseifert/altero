# Why altero exists

altero is for people and organizations that need the Zotero synchronization
service on infrastructure they control. Libraries, notes, annotations, group
data and attachments can stay on their own server.

## Why not just WebDAV?

WebDAV stores attachment files for a personal Zotero library. Library data
still synchronizes through zotero.org, and group files cannot use WebDAV.

altero provides both data and file synchronization for personal and group
libraries. It works with unmodified Zotero Desktop. Its
[browser interface](web-interface.md) also supports everyday reference management.

## What running your own server involves

A basic installation has one application, a database and an attachment directory.
SQLite suits small personal installations; PostgreSQL suits concurrent users.
No separate search service, cache or queue is required.

You take responsibility for hosting, HTTPS, backups, upgrades and account
management. The browser provides routine administration, including storage
reports and retention settings. Institutional sign-in and finer group
permissions can help a shared installation fit local needs.

An instance administrator manages the installation without automatically gaining
access to everybody's library contents.

## Compatibility comes first

The normal Zotero desktop application must be able to exchange changes through
altero. When published API documentation and actual server behavior disagree,
altero follows the behavior clients depend on. Additional features must preserve
that compatibility.

Mobile apps need a separate build pointed at altero because they do not offer
a server setting. altero does not distribute such builds. See
[Mobile apps](clients.md#mobile-apps).

## Is altero right for you?

Hosted synchronization at zotero.org remains convenient and supports Zotero's
development. altero is an independent project for users who need another
deployment model; it is not supported by Zotero.

Keep a current backup of important libraries and don’t rely on altero as your
only copy yet. Read [What works](status.md) for capabilities and limits, then
[try a local instance](getting-started.md) with disposable data.
