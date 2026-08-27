# Accounts and personal settings

Use these screens to register or sign in, manage your own account, review API keys, and choose language and time-zone settings.

## Common tasks

- Change your password, display name or email address in **Settings**.
- Review and revoke API keys in **Settings → API keys**.
- Review and disconnect third-party applications in **Settings → Connected applications**.
- Choose the interface language and time zone in account settings.
- If registration is closed, ask an instance administrator to create the account or use an invitation link.

## Detailed behavior

The sections below retain the technical and behavioral detail needed for troubleshooting and development. You can stop after the task summary if you only need to use the feature.

### Accounts

Registration in the browser opens for three cases, and for nothing else:

- **The first account.** Always, so a fresh container is reachable by its owner
  without shell access. It closes again the moment that account exists.
- **`ALTERO_OPEN_REGISTRATION`**, if the deployment sets it. Off by default: an
  instance is somebody's own server rather than a service, and an open form on
  one reachable from the internet is an invitation to strangers.
- **An address somebody invited.** Whoever holds an unanswered invitation to a
  group may make an account with the address it was sent to, and nobody else
  may. Without this the emailed link landed on a form that refused it, which
  made inviting a person who is not here yet unreachable on any instance that
  had not opened registration outright.

The sign-in page offers a register link only for the first two: an invitation
opens the door for one address, and advertising the instance as open would
promise a form that refuses almost everybody. The link in the invitation goes
straight to the form.

Every other account is made by an instance administrator — under
**Administration → Accounts** in the browser, or with `altero user add` and
`altero user password <username>` from a shell. See
[administration.md](../administration.md).

**A forgotten password** is offered on the sign-in page only where the
deployment set `ALTERO_PASSWORD_RESET` and configured a relay; otherwise an
administrator issues the link. The form says the same thing whatever it finds —
"if an account here uses that address, a link is on its way" — because a page
that said otherwise would answer, one address at a time, which addresses have
accounts here. It works only for an address that has been confirmed: nobody has
proved they hold an unconfirmed one, and honouring it would make a typo at
registration somebody else's way in.

**Signing in through somebody else's directory** is offered where an operator
has configured one — see [administration.md](../administration.md#sign-in-providers).
The button appears above the password form, which stays: federation is an
addition, not a replacement, and an instance keeps its local accounts.

What a completed sign-in produces is a browser session, exactly the one a
password produces. **A Zotero client still holds an API key, and still gets it
from Settings → API keys.** That is the boundary rule doing its job rather than
a gap: the v3 API takes keys and nothing else, and no amount of single sign-on
changes it. It is the first question an institution asks, so it is answered
here rather than in a footnote.

An account here is matched to a directory by its **subject** — the opaque
identifier the directory issues — and never by an email address. A directory
that can assert an address would otherwise be able to take the account holding
it, which is the usual way federated sign-in is broken into. So a first sign-in
that nobody has connected either makes a new account, where the operator allows
that, or is refused; it never adopts one. Connecting a directory to an account
you already have is done from **Settings → Sign-in and security**, while signed
in, exactly as enrolling an authenticator is.

Accounts that predate this interface keep working exactly as they did. They
have no password until one is set, which means they can sync but cannot sign in
to the browser.

### Account settings

Sections behind a side panel — profile, sign-in and security, language and time
zone, API keys, connected applications, import and export — rather than one page
of cards, which at this many cards means scrolling past the authenticator and
every key on the account to reach the time zone.

The panel is the library's: the same rows, the same fill on the current one, so
the two screens read as one application. Which section is showing is in the
path (`/app/settings/keys`) rather than in component state, so a section can be
linked to and the back button walks them. The slugs are not translated; an
unknown one falls back to the first section rather than to an empty page.

Display name, password, email address, an authenticator app, and the list of
signed-in browsers, each of which can be signed out on its own. Anything that
touches a credential asks you to prove again that the browser is yours: a
session cookie is what somebody who borrowed an unlocked laptop already has.
The usual proof is the current password, and once it has been given it stands
for five minutes, so changing a password and then making a key is one prompt
rather than two. An account that has no password — one an administrator created
and never set one for — proves itself the other ways it can, and is not shut
out of its own settings for lacking a credential it was never given.

Setting up an authenticator is two steps. The secret is stored but ignored
until a code from the app proves it works, so an interrupted setup cannot lock
the account.

**A passkey signs you in on its own.** Your device checks it is you — a
fingerprint, a face, a PIN — and there is no password to steal, phish or
reuse. It is the strongest way in this interface has, and the sign-in page
offers it before the password form.

That is why it is not followed by a second factor: the authenticator has
already established both that somebody is present and that it is you, and
asking for a code afterwards would add something weaker than what was just
presented. A passkey also counts as having proved yourself, so the things that
would otherwise ask for your password again — making an API key, changing your
address — do not ask twice.

**No username is typed.** The browser offers whichever passkey it holds for
this site, and the assertion says whose it is. There is no form here that
behaves differently for a name that exists, so the sign-in page cannot be used
to ask who has an account.

Adding one asks for your password, because a passkey is a way *in* rather than
a hurdle in front of one — the same rule an API key follows. Removing one asks
too, and the last way in cannot be removed: an account with no password and one
passkey would otherwise be able to lock itself out of a library nobody else can
reach. Where a passkey lives on a single device rather than being backed up,
the list says so, which is worth knowing when it is your only one.

Passkeys need `ALTERO_PUBLIC_URL` and are not offered without it. A passkey is
bound to the address it was enrolled at, and an instance that guessed that from
whatever request arrived would make passkeys that stop working the day the
address changes — silently, weeks later. The sign-in page asks the server
rather than assuming.

**A code by email** is the second factor for anyone with no authenticator app,
and the way back in for anyone who had one and lost the phone. It needs a
confirmed address and nothing else — there is no secret whose working has to be
proved, only an address somebody proved they could read — so turning it on is
one step rather than two. It is a weaker factor than an app, and where both are
enrolled the app is asked for; **Use a code by email instead** is on the
sign-in screen, which is what makes it a recovery path rather than a
convenience. Before it existed, an account with an unreachable authenticator
had exactly one way back: find whoever runs the server.

The code lasts ten minutes, works once, and works only in the browser that
asked for it — so somebody who reads the message cannot use it from their own
machine. Five wrong guesses throw it away rather than leaving six digits
standing to be walked through, and asking for another stops the one before it
working.

### API keys

Settings lists the keys on the account: what each may do, when it was made, and
when and from where it was last used. That last part is what makes the list
worth having — a key never used, or last seen from an address nobody
recognizes, is one to remove.

Creating a key asks for the password, because it hands out a new credential.
Revoking one does not: the moment somebody reaches for that is the moment a key
has leaked, and a password prompt there is friction in the wrong place. A key
is shown in full exactly once, when it is created, and as four characters
afterwards.

Use is recorded at most once a minute per key, and immediately when the address
changes. It is a convenience for deciding what to revoke, not an audit log.
Behind a reverse proxy the address recorded is the proxy's until
`ALTERO_FORWARDED_ALLOW_IPS` names it; see [deployment.md](../deployment.md).

### Connected applications

Separate from API keys next door, because they are different things and saying
so is the point. A key is a credential you made and pasted somewhere. An
application is somebody else's software that you allowed to reach this account,
with a named set of permissions you were shown and approved.

Each entry says what the application may do — in sentences rather than scope
names — when it was connected, and whether it is in use right now. Disconnecting
one takes effect immediately: its tokens go with it rather than running out an
hour later, because somebody who has decided an application should stop meant
now.

Approving happens on its own screen, reached when an application sends you here.
That screen has no password field and never will: you sign in the ordinary way
first, with whatever second factor, passkey or institutional sign-in your account
has, and only then are you asked what to allow. A second way to prove who you are
would be a second place for the second factor to be forgotten.

How an operator registers an application, and what a client developer needs:
[Connecting other applications](../oauth.md).

### Language and time zone

The interface speaks English, German, French, Spanish, Portuguese, Italian,
Dutch, Danish, Polish, Russian, Japanese and Chinese — fifteen catalogs,
because three of those are written differently in different places and are
carried twice: American and British English, Brazilian and European Portuguese,
Simplified and Traditional Chinese. They are the same three Zotero splits.
Both settings live on the account rather than in the browser, so signing in
from another machine gives you your own language rather than that machine's,
and both default to following the browser — which is a setting in itself, not
an unset value.

Dates and times are formatted from those two together. Choosing a language does
not move your date format to another country: with German chosen on a machine
set to `de-AT`, the words are German and the dates Austrian. Timestamps the
server records — when an item was added, when a key was last used — are stored
as UTC and shown in your zone, so an item added at 22:30 UTC is the third of
the month in Berlin and the fourth in Tokyo.

No date rule is written down anywhere in altero, and adding a language does not
add one. `web/src/formats.ts` hands the formatting tag and the zone to `Intl`
and takes what the CLDR data in the browser gives back, so Danish separates the
hour with a full stop — *4. apr. 2019, 00.30* — Russian ends a date in *г.*,
Chinese and Japanese write 2019年4月4日, and none of that is altero's doing.
Sizes go the same way, which is why a Russian reader is told *1,5 МБ* although
no catalog holds a byte unit. What the tests in `stores/locale.spec.ts` hold
is the one thing that *is* ours: that each language reaches `Intl` at all, a
wrong tag being the failure that would otherwise show every reader English
dates in a translated page.

A tag is narrowed to the catalog that answers it, and what gets dropped
depends on the language. For the twelve carried once, the region goes: `de-AT`
is German, and the region goes on reaching dates because the browser supplies
that separately. For English, Portuguese and Chinese the region is what decides
the words, so it is kept — a British reader empties the Bin rather than the
Trash, a Brazilian saves an *arquivo* rather than a *ficheiro*, and Simplified
and Traditional Chinese do not share a script.

Three questions follow, and `services/locales.py` answers each rather than
leaving it to chance. A **bare `en`, `pt` or `zh`** goes where CLDR's likely
subtags send it — `en-US`, `pt-BR`, `zh-CN` — which is an answer that can be
cited rather than an opinion about who owns a language. A **territory with no
catalog of its own** is sent to the one it reads: Australia, Ireland, India,
New Zealand and South Africa spell as Britain does, Hong Kong and Macau read
Traditional characters, and Angola and Mozambique write European Portuguese.
Anything else falls back to the language's default variant, so `en-CA` is
American rather than nothing at all.

The browser carries the same two tables, in `web/src/i18n.ts`, because it has
to resolve a tag before it has asked the server anything — the sign-in page has
no account to ask about. `tests/test_locales.py` reads both and fails if they
disagree, which would render one language and store another.

Choosing a variant still does not choose a date format. The formatting tag is
matched on the *language*, so an account set to 简体中文 on a machine in Taipei
gets Simplified words and Taiwanese dates, by the same rule that gives German
words Austrian dates. The schema's display names are asked for with the words'
tag instead, so a column heading and the detail pane cannot end up in different
Englishes.

What an item type, a field or a creator type is called is not translated here
at all: those names come from the schema, which carries Zotero's own
translations in 48 locales, and they follow the account's language — the item
list's column headings included. Where the interface's own messages name
something Zotero also names, they use Zotero's word for it, so the two
applications read as one vocabulary.

A personal library is called **My Library** everywhere the interface names one
— the sidebar, the dialogs, and the export and restore lists in settings — from
one function in `web/src/librarylabel.ts`. It is one function because it was
briefly two: the sidebar took Zotero's word for it while Import and export went
on printing the account holder's own name, which is one library under two names
on two screens of one application. The exception is the library an *archive*
was made from, which is named as its manifest recorded it: that one may be on
another server and belong to somebody else.

Where a row names something Zotero also names, the words are Zotero's own,
taken from `chrome/locale/<lang>/zotero/zotero.properties` and `zotero.ftl` in
the client rather than translated again here: `pane.collections.library`,
`.groupLibraries`, `.publications`, `.duplicate`, `.unfiled` and `.trash` for
the sidebar, `recently-read` and `menu-restoreToLibrary` for the two the client
keeps in Fluent. So the German sidebar says *Eintragsdubletten* and *Einträge
ohne Sammlung*, which are not the phrases anybody would arrive at unprompted —
and are what the desktop client next to it says. The gaps are the rows Zotero
itself has not translated: *Recently Read* in Japanese, Danish and Dutch, and
*Items* in Danish. Leaving English standing in those sidebars would be worse
than translating them here, so altero does — 最近読んだ項目, *Læst for nylig*,
*Onlangs gelezen*, *Elementer* — following the word the rest of that locale
already uses.

That vocabulary rule is also why "Restore to Library" has a message of its own:
"Restore" alone is what the settings page calls putting an archive back, and
one message for both had German offering to replay an item from a backup.

Counting is not the same everywhere, and a message with a number in it says so.
English separates one from many, and German, French, Spanish, Portuguese,
Italian, Dutch and Danish separate it the same way; Japanese and Chinese inflect
nothing and write the one form twice, so the branch that gets picked does not
matter. Polish and Russian have a third form for the small counts — *2 elementy*
against *5 elementów*, *2 записи* against *5 записей* — so their catalogs
carry three branches and `pluralRules` in `web/src/i18n.ts` chooses between
them. A catalog written with English's two would be wrong on every count from
2 to 4, so `locales.node.spec.ts` holds each catalog to the number of forms
its own language has rather than to English's — a check against English would
have called "2 elementów" correct.

The translations beyond American English are mine rather than a native
speaker's, and are worth reviewing before an institution relies on them. That
includes British English: `en-US.ts` is the list every other catalog is
checked against, and `en-GB.ts` is a translation of it like any other, written
out in full rather than left to fall back so that a sentence reworded in English
is caught there too. Adding another language is one file in `web/src/locales`,
plus its tag in `services/locales.py` and in `MESSAGES` in `web/src/i18n.ts` —
and a plural rule beside it if the language needs more than two forms.
`tests/test_locales.py` and `web/src/locales/locales.node.spec.ts` fail if the
server's list and the catalogs ever disagree, or if a catalog drifts from
the English one.
