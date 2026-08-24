# Groups, invitations and activity

The browser lets members see their groups, administrators manage membership and policy, and users review activity or opt into notifications.

## Common tasks

- Create or administer groups from the **Groups** screen.
- Invite a person by email address; they can accept in the interface or through the invitation link.
- Review group activity in the authenticated interface.
- Choose which group changes should generate notifications or email digests.

## Detailed behavior

The sections below retain the technical and behavioral detail needed for troubleshooting and development. You can stop after the task summary if you only need to use the feature.

### Groups

A screen of its own, reached from the header. It lists the groups the account
belongs to with how many people and items are in each and what this account may
do there, and it creates one — which is open to anybody signed in, a group
being a library of your own rather than something to be granted.

Opening a group shows its members and, to an administrator, the settings that
decide what everybody may do: whether the group is private or public, who may
read the library, who may add and change items, and who may upload files. Those
last three are Zotero's own `libraryReading`, `libraryEditing` and
`fileEditing`, enforced by the server rather than merely recorded — see
[administration.md](../administration.md#group-policy).

Beside those, each member carries a permission of their own: whatever the group
allows, read only, only their own items, or add but not remove. Zotero has no
such notion — its groups decide who may edit once, for everybody — and these
are the three finer roles the forums have asked for since 2010. A permission is
a ceiling under the group's policy rather than a way past it, an administrator
cannot be given one, and an invitation can carry one so that being asked to
read a library and being asked to work on it are different invitations.
[compatibility.md](../compatibility.md#finer-roles-for-one-member) has the table
and the two decisions behind it — how a read-only member is expressed to a sync
client, and why the other two show up as sync errors when a desktop client
tries anyway. The item list here knows about all of them and does not draw a
control the server would refuse.

What a screen offers follows the role the *server* resolved and sends back with
the group. Deciding it in the browser would mean a second implementation of the
permission rules, drifting against the one that actually refuses the request,
and a control that will be refused is a promise the interface cannot keep. So a
plain member sees no policy controls and no delete button at all.

Three things need more than a click. Handing a group on and deleting one are
the owner's alone, and deleting asks first, because everything in the group
goes with it and there is no trash around a library. Leaving is nobody's
permission but your own: a member who had to ask would be in a group they
cannot get out of.

The same operations are available to an API key and to the command line;
`services/groups.py` is the one place that decides any of it, so a role means
the same thing whichever door set it.

### Notifications and invitations

An administrator of a group library can invite an email address to it. If that
address belongs to an account here, the invitation appears in that person's
notifications and can be accepted or declined in the interface; if it does not,
the emailed link carries a token and whoever registers with that address can
accept it afterwards.

Both channels are used deliberately. Mail may be unconfigured, unconfirmed,
filtered or simply lost, and an invitation that exists only in an inbox is one
that frequently never arrives.

The emailed link lands on a screen that reads the invitation **without a
session**: somebody with no account here has to be able to see what they were
asked to join before deciding to make one. Answering it still needs one, and
the server still checks the address it was sent to — holding the link is not
the same as being the person it was offered to. Signing in or registering from
that screen comes back to it, so the thing they came to answer is the next
thing they see.

#### What has happened in a group

The group's panel opens with its recent activity: who changed what, and when.
Every member sees it. It was asked for as a way of keeping up with a shared
library, and restricting it to the people who run the group would make it a
supervision tool instead.

An entry is one write request — the same unit as a library version — and it
names what the request touched: "4 items added or changed", then the titles.
The first three are shown and the rest summarised, because a request may carry
fifty objects and fifty titles under one line would bury the log rather than
fill it in.

The names are **what things were called at the time**, stored with the entry
rather than looked up when it is read. An item renamed next week must not
rewrite what it was called last week, and a deleted item has nothing left to
look up at all — which is the entry most worth being able to read.

The wording matches the digest that arrives by mail, so one change reads the
same way whichever way somebody hears about it. A change nobody can be
attributed to reads "Somebody": a write can reach a group library with a key
that names no person, and that is still something that happened.

What an entry does not say is what *about* an object changed. Recording that a
title went from one string to another means storing both, for every field of
every write; that is a different feature with a very different cost, and it is
not built.

This is the read side of the record the notification digest already keeps, so
it costs no extra writing. Upstream has wanted the same thing since
[dataserver#89](https://github.com/zotero/dataserver/issues/89) in 2019 and
offers a group RSS feed instead, which shows neither what was modified nor what
was deleted.

Alongside it, an item in a group library carries who added it and who last
changed it. That part is upstream's own.

#### Hearing about a group

The same panel carries four switches for what the group should tell you about:
items added or changed, items deleted, people joining or leaving, and
collections. All off until somebody turns one on, per group rather than per
account — being in five groups and caring about one is the ordinary case, and
one switch for all of them would make that a choice between silence and five
groups' worth of noise.

This is the one thing in the group panel a plain member can change. It is your
own subscription: there is no address to point somebody else's notifications
at, and an administrator deciding what the members are mailed about is not a
power anybody asked for.

What arrives is a digest rather than a running commentary, and what decides
when it arrives is in [email.md](../email.md#group-notifications). The interface
shows the same thing in the notifications panel whether or not mail is
configured.
