# Connecting a Zotero client

## Point a test installation at it

altero is not finished, and a sync sends the client's data to it. Use a test
profile rather than the installation holding a library you care about.

## The desktop application

The client's API base URL is a hidden preference. In Zotero, open
**Settings → Advanced → Config Editor**, accept the warning, and set:

    extensions.zotero.api.url = http://localhost:8000/

The trailing slash matters. Set one more, in the same editor:

    extensions.zotero.streaming.url = ws://localhost:8000/stream

`api.url` does not redirect the streaming API. The client resolves that
separately, falling back to a compiled-in `wss://stream.zotero.org`, and sends
your API key to it — a key that grants full access to your private library
would go to zotero.org, which rejects it as unknown and may log it. See
[compatibility.md](compatibility.md).

altero serves that socket itself, at `/stream`, so pointing the preference at
it is both the safe answer and the useful one: the client is told the moment a
library changes instead of waiting for its next poll. Over TLS the scheme is
`wss://`. If you would rather not use it at all, turn it off instead — what
must not be left is the compiled-in default:

    extensions.zotero.streaming.enabled = false

Then restart Zotero and open **Settings → Sync → Link Account**.

## How the client gets its key

Zotero authenticates by opening a page in the browser and polling until it is
approved. That page is this server's own [web interface](web-interface.md):
sign in, confirm with your password, and the client picks up its key on the
next poll. Nothing else is needed.

Confirming asks for the password even though you are already signed in. The key
it creates reads and writes every library the account can reach and keeps
working until it is removed in Settings, so a link somebody sends you should
not be enough on its own.

Without the web interface built, that page serves the command-line instructions
instead, and they still work:

```sh
uv run altero login list
uv run altero login approve <token> <username>
```

The client picks the key up on its next poll — usually within a few seconds —
and syncing proceeds normally. `login approve` issues a key unless you point it
at an existing one with `--key`.

Either way the key covers group libraries as well as the personal one, which is
what the client expects to sync.

## Two of them at once

Two installations on one machine are two profiles and two data directories,
which is how the sync itself gets tested rather than only replayed:
[testing-two-clients.md](testing-two-clients.md).

## Mobile is not possible

The desktop application is the only client this works with. Zotero for iOS and
for Android compile `https://api.zotero.org` into the build — a
`buildConfigField` on Android, a constant on iOS — with no preference, no debug
screen and no runtime override. A phone reaches another server only from a
patched build, which this project will not produce.

[motivation.md](motivation.md) sets out the evidence, why the non-goal it runs
into is worth keeping, and why asking upstream is not the missing step.
