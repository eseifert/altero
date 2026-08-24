# The web interface

altero includes a browser application at `/app/` for account management, library browsing, groups, sharing and instance administration.

**Important boundary:** the browser session does not authenticate the Zotero v3 API. Zotero Desktop continues to use an API key.

The web interface is a companion to Zotero Desktop, not a replacement for the full reference manager. In particular, bibliographic field editing remains a desktop task.

## What you can do

| Area | Main capabilities | Detailed guide |
| --- | --- | --- |
| Accounts and settings | Sign in, password/email settings, API keys, language, time zone, second factors | [Accounts and personal settings](web/account.md) |
| Library | Browse, search, collections, item actions, tags | [Browsing and organizing a library](web/library.md) |
| Publishing and sharing | My Publications, profile pages, shared collections | [Publishing and sharing](web/sharing.md) |
| Data transfer | Move from zotero.org, backup/restore archives, exports | [Moving, importing and exporting data](web/data-transfer.md) |
| Groups | Membership, invitations, activity, notifications | [Groups, invitations and activity](web/groups.md) |
| Instance administration | Accounts, storage, retention, sign-in providers | [Administration](administration.md) |
| Contributor details | Build commands, design system, known browser gaps | [Web implementation notes](web/implementation.md) |

## Accounts

Registration and personal settings are documented in [Accounts and personal settings](web/account.md).

Registration is not generally open by default. It is available for the first account, when the instance enables open registration, or for an address with a group invitation.

## Account settings

Users can manage their own credentials, email address, second factors and signed-in sessions from Settings. See [Accounts and personal settings](web/account.md).

## API keys

API keys used by Zotero Desktop can be reviewed and revoked from the browser. See [Accounts and personal settings](web/account.md).

## Language and time zone

Language and time-zone preferences belong to the account, so they follow the user across browsers. See [Accounts and personal settings](web/account.md).

## Browsing a library

The browser presents a Zotero-like library view with collections/tags, an item list and item details. See [Browsing and organizing a library](web/library.md).

## Collections

Collections can be created, renamed, moved and removed in the browser. See [Browsing and organizing a library](web/library.md).

<a id="sharing-one"></a>
### Sharing one collection

A collection can also be shared by link without exposing the whole library or requiring the recipient to have an account. See [Publishing and sharing](web/sharing.md).

## Items

The browser supports filing, trashing, restoring, deleting and copying items. Editing bibliographic fields is still a Zotero Desktop task. See [Browsing and organizing a library](web/library.md).

<a id="writing-items-out"></a>
### Exporting items

The browser can write Zotero-supported export formats and CSL JSON for a library, collection or selection. See [Moving, importing and exporting data](web/data-transfer.md).

## My Publications

My Publications lets a user publish selected work under the terms collected by the Zotero-style publishing flow. See [Publishing and sharing](web/sharing.md).

## Profile pages

Published work appears on the user's profile page subject to the audience chosen by that account. See [Publishing and sharing](web/sharing.md).

<a id="who-can-see-it"></a>
### Publication visibility

Visibility is controlled by the account's publication/profile settings. The detailed behavior is in [Publishing and sharing](web/sharing.md).

<a id="by-touch"></a>
### Touch interaction

Touch and pointer interaction details are documented in [Browsing and organizing a library](web/library.md#by-touch).

## Tags

Tags can be renamed across a library from the browser. See [Browsing and organizing a library](web/library.md).

## Moving in from zotero.org

A personal library can be copied from zotero.org while preserving keys and versions the desktop client already knows. See [Moving, importing and exporting data](web/data-transfer.md).

## Import and export

A complete altero archive is for backup or moving between compatible instances. Ordinary export formats are for other applications. See [Moving, importing and exporting data](web/data-transfer.md).

## Administration

Instance administrators get a separate Administration area for accounts, storage, retention and sign-in providers. The role does not automatically grant access to every library. See [Administration](administration.md).

## Groups

Users can view groups; group administrators can manage membership and policy. See [Groups, invitations and activity](web/groups.md).

## Notifications and invitations

Group invitations, activity and opt-in notifications are documented in [Groups, invitations and activity](web/groups.md).

<a id="what-has-happened-in-a-group"></a>
### Group activity

The authenticated activity view can name the items and collections involved in changes. Email digests intentionally contain only counts. See [Groups, invitations and activity](web/groups.md).

<a id="hearing-about-a-group"></a>
### Group notifications

Members choose their own notification subscriptions. See [Groups, invitations and activity](web/groups.md) and [Email](email.md#group-notifications).

## Design

The browser follows the altero design system. Contributor-facing details are in [Design system](design.md) and [Web implementation notes](web/implementation.md).

## Not built yet

The browser is intentionally not a complete Zotero Desktop replacement. See [Web implementation notes](web/implementation.md) for the current browser-specific gaps and [What works](status.md) for the server feature status.
