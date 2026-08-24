# Publishing and sharing

altero provides two different sharing models: **My Publications** publishes selected work on a profile page, while a shared-collection link exposes one collection to anyone who holds the link.

**Audience:** Zotero users

## Common tasks

- Use **My Publications** when you want work to appear on your profile page.
- Choose the audience for published work in your profile settings.
- Use a collection-sharing link when you want to expose one collection without requiring an altero account.
- Review publication rights/licence choices before publishing files.

## Detailed behavior

The sections below retain the technical and behavioral detail needed for troubleshooting and development. You can stop after the task summary if you only need to use the feature.

### My Publications

Dropping a work on the **My Publications** row publishes it, and is the one
drop that asks before it acts. It has to: publishing is not filing. The
questions are the desktop client's, in the client's own order, and so are the
rules they set — [compatibility.md](../compatibility.md#publishing-from-the-browser)
lists each rule beside the line of `Zotero.Items.addToPublications` it comes
from.

**What goes along.** Files and notes are separate answers, and each is offered
only where the item has one. Link attachments always go, since a link is a URL
the item's own fields already carry; a *linked file* never does, because this
server does not hold its bytes and so could not publish them.

**Whether the work is yours.** Nothing advances until that is confirmed, and
the sentence changes when files are included: distributing somebody's PDF is a
larger claim than listing their paper.

**Under what licence.** Only when files are being published — there is nothing
else to license. Reserved rights, a Creative Commons licence, or the public
domain; Creative Commons then asks the two questions that decide which of the
six it is, defaulting to the most restrictive of each pair. The licence's name
goes into the item's **Rights** field, unless the field already says something
and “Keep the existing Rights field” is ticked — in which case there is nothing
left to ask and the wizard ends there. The name shown is the name that will be
stored, in English, and
[compatibility.md](../compatibility.md#publishing-from-the-browser) says why it is
not translated.

The whole of it is one request and one library version, however many notes and
files go with the work: publishing a work and its files is one decision, and a
client syncing afterwards sees it as one.

**Changing the licence afterwards** is the Rights field, which the detail pane
can edit — the pencil beside it, or “Not stated — say what it is” where the
item says nothing yet. That is where the desktop client changes a licence too:
its wizard refuses to run a second time on the same item
(`collectionTree.jsx`: “Item … already exists in My Publications”), and Rights
is an ordinary field in its Info pane. The dialog offers the same eight
licences the wizard does, by code and by name, and free text for everything
else a Rights field says — “© 1974 the author” as readily as a licence.

It is the only field this interface writes, and it states the version it is
replacing: filing and trashing are add-and-remove errands the server works out
against what is stored, so a stale page cannot express a wrong one, but typing
over a licence that another client changed while the page sat open is a lost
write. A stale edit is refused rather than applied.

**Taking it out again** is `Delete` in the My Publications view, or a button in
the detail pane, and it asks first. The work leaves the published list with its
published notes and files — including any that have since been trashed, which
were still published until now — and stays in the library with everything it
holds. Its `Rights` field is left as it is: a licence already granted is not
withdrawn by hiding the page. Inside the My Publications view a single note or
attachment can also be shown or hidden on its own, which is what the desktop
client offers there and nowhere else.

A group has no My Publications and none of this appears in one: publishing is
something an account does with its own library, and the server refuses it for a
group item in any case.

### Profile pages

Publishing something has to publish it *somewhere*. The desktop client's wizard
says so in every language it ships — "Items you add to My Publications will be
shown on your profile page" — and that page is what `/app/u/<username>` is.

It is a list rather than the library's three panes, because somebody reading it
is reading a bibliography: each entry opens in place to show the abstract, where
the work appeared, the licence its files are under, and the files themselves.
Everything on it goes through the same services and the same serialiser as the
library view, so an item on a profile page is the item a syncing client
receives; only which items exist differs, and that is `inPublications` and
nothing else. Notes and files appear only if they were published with the work —
which the wizard asked once, and does not ask again.

The licence links to the licence. A **Rights** field holding one of the eight
the wizard offers is shown as a link to the deed; anything else is shown as the
text it is, because guessing a URL for "© 1974 the author" would be inventing a
permission. Files are served from the profile itself, under the same rules
upstream applies — its own permission check falls through to `canAccessObject`,
which passes a published item, "for My Publications files".

Each entry can also be cited, in the same six styles the library's detail pane
offers and through the same renderer on the server. A list of somebody's work is
where a reader is most likely to want a citation of it, and the alternative was
a second CSL implementation, in a second language, to disagree with the first.

**The address is `/app/u/<name>`**, not `/app/<name>`, which is where zotero.org
puts it. A bare path would collide with the interface's own routes, so an
account called `settings` or `library` would have no page at all and every route
added later would quietly claim a username. The name is matched without regard
to case, and upstream's slug is accepted too, so a link formed the way
zotero.org forms one still arrives.

#### Who can see it

Upstream has no such question: zotero.org is a service, its profiles are public,
and the dataserver serves `/users/<id>/publications/items` to whoever asks. This
server is somebody's own, and "published" on it can reasonably mean something
narrower — so the account decides, in settings under **Profile**:

- **Anyone**, with no account here. Upstream's behaviour, and what every account
  starts as, so nothing changed for work already published.
- **People with an account here.** The middle answer, and the reason the setting
  exists: an instance shared by a research group is neither the open web nor a
  private drive.
- **Nobody.** The page is hidden. The items stay in My Publications and stay
  flagged, so turning it back on publishes exactly what was there before.

The choice governs the v3 endpoints as well, not only the browser: a page that
refused a stranger while `curl /users/1/publications/items` listed the same work
would be a decoration rather than a setting. In v3 terms, **users** means any key
this server issued and **nobody** means a key that could read the library anyway
— so the owner's own desktop client goes on syncing My Publications whatever the
page says. See
[compatibility.md](../compatibility.md#who-may-read-my-publications).

A page that may not be read answers 404, exactly as an unclaimed name does.
Distinguishing them would turn the address into a way of asking which usernames
have accounts behind them; the page itself says the useful half — that some
profiles are shown only to people signed in — without the server disclosing
anything.
