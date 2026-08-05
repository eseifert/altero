# Sending email

altero sends very little mail, and works without sending any. Configuring a
relay is optional, and what it buys is described below before the settings, so
that the decision is about what an instance needs rather than about which
variables exist.

## What is sent, and when

Five kinds of message, all plain text. Four are triggered by something a person
just did:

- **Confirm your email address**, on registration, when the address on an
  account is changed, and on request from the account settings. The link is
  good for 24 hours.
- **An invitation to a group library**, when an administrator invites an
  address from the browser. The link carries a token and can be read without an
  account, so somebody who is not here yet can see what they were asked to join.
- **Your password was changed**, after a password change in the browser.
- **An authenticator app was added / removed**, after enrolling or disabling
  TOTP.

The last two are security notices, and they go **only to a confirmed address**.
An address nobody has proved they hold may be somebody else's, and a notice
about a password change is exactly the message not to send to a stranger. So an
account whose address is unconfirmed silently gets no security mail — which is
the other reason the confirmation message matters.

The fifth is the exception, and the only message not caused by the person
receiving it:

- **New activity in a group library**, to members who asked for it, once the
  library has been quiet for a while. Off for everybody until they turn it on.
  See [Group notifications](#group-notifications) below.

Nothing else is sent. There is no password reset by email: an account locked out
of the browser is recovered from the command line with `altero user password
<username>`, which is what the "if this was not you" notice tells the owner to
ask for. There is no marketing, and nothing goes to somebody who did not either
cause it or ask for it.

## Without a relay

With no relay configured — the default — messages are written to the log at
`WARNING`, in full, saying why:

```
No SMTP relay is configured (set ALTERO_SMTP_URL), so this message was not
sent. It is written out here instead.
  To:      ada@example.org
  Subject: Confirm your email address for altero
  ...
    https://altero.example.org/app/verify?token=...
```

That is a delivery channel rather than a failure. A self-hosted instance often
has no relay at all, and whoever has just started a container still has to be
able to read the confirmation link and finish registering:

```sh
docker compose -f docker/compose.yaml logs altero | grep -A6 'was not sent'
```

The same code path runs either way, so the path that works when mail is broken
is not one that only ever runs when something is already wrong.

An instance can stay here indefinitely. Confirmation is optional (an unconfirmed
account signs in, syncs and reads its library exactly as a confirmed one does),
and invitations also appear in the recipient's notifications inside the
interface whenever the address belongs to an account here. What is lost is
security notices and inviting somebody who has no account yet.

## Configuring a relay

Three settings, as `ALTERO_`-prefixed environment variables or in `config.py`:

| Setting | Environment variable | What it does |
| --- | --- | --- |
| `SMTP_URL` | `ALTERO_SMTP_URL` | Where to hand messages. Empty logs them instead. |
| `MAIL_FROM` | `ALTERO_MAIL_FROM` | The `From` address. Defaults to `altero@localhost`. |
| `PUBLIC_URL` | `ALTERO_PUBLIC_URL` | Absolute base URL the links point at. |

```sh
ALTERO_SMTP_URL='smtp://altero%40example.org:s3cret@mail.example.org:587' \
ALTERO_MAIL_FROM='altero <altero@example.org>' \
ALTERO_PUBLIC_URL='https://altero.example.org' \
    uv run altero
```

Or in `config.py`:

```python
SMTP_URL = "smtp://altero%40example.org:s3cret@mail.example.org:587"
MAIL_FROM = "altero <altero@example.org>"
PUBLIC_URL = "https://altero.example.org"
```

The URL is parsed and checked when the configuration is read, so a typo is a
start-up failure — visible when it is made, rather than when somebody is waiting
for a confirmation that never comes.

### The URL

```
smtp://[username[:password]@]host[:port]
smtps://[username[:password]@]host[:port]
```

- **`smtp://`** connects in the clear and then upgrades with `STARTTLS`. The
  default port is **587**, the submission port.
- **`smtps://`** is TLS from the first byte. The default port is **465**.

The upgrade on `smtp://` is opportunistic: if the relay does not offer
`STARTTLS`, altero logs a warning and sends anyway. That is for the common case
of a relay on the same host or the same container network, where refusing to use
it would leave the deployment unable to send anything at all. Over a network you
do not control, prefer `smtps://`, which never falls back.

Credentials are percent-encoded, because a username is usually an email address
and a password is whatever the provider generated. `@`, `:`, `/`, `#`, `?` and
`%` must be escaped — `altero@example.org` becomes `altero%40example.org`. A
password pasted in raw and containing an `@` will silently produce the wrong
host.

Omit the credentials entirely for a relay that does not want them:

```python
SMTP_URL = "smtp://localhost:25"
```

### The `From` address

`MAIL_FROM` accepts a bare address or a display name with one. Set it to
something the relay is willing to send as: a provider that is authenticated as
one domain and asked to send as another will usually reject the message, and a
recipient's spam filter will reject what SPF and DKIM do not cover. The default,
`altero@localhost`, is deliberately not deliverable — it is a placeholder, not a
suggestion.

SPF, DKIM and DMARC are the relay's business, not altero's. altero authenticates
to a relay and hands it a message; everything about how that message is signed
and who is allowed to send it belongs to whatever is configured at the other end
of `SMTP_URL`.

### The public URL

Every message except the security notices carries a link, and a link that points
nowhere reachable is a message that does nothing.

Without `PUBLIC_URL`, links are built from the address the request arrived on.
That is right for a single host reached directly, and wrong behind a proxy that
rewrites the host: the link then points at the internal name or port, which
nobody outside can open. Set it to the URL people actually type, with scheme, no
trailing path:

```python
PUBLIC_URL = "https://altero.example.org"
```

This is separate from `FORWARDED_ALLOW_IPS`, which decides which address is
*recorded*; see [deployment.md](deployment.md#behind-a-reverse-proxy). Behind a
proxy you generally want both.

## In a container

`docker/compose.yaml` already passes all three variables through, so nothing in
it needs editing. Write **`docker/.env`** — beside the compose file — and
restart:

```sh
cat > docker/.env <<'EOF'
POSTGRES_PASSWORD=something-other-than-the-default
ALTERO_SMTP_URL=smtps://altero%40example.org:s3cret@mail.example.org
ALTERO_MAIL_FROM=altero@example.org
ALTERO_PUBLIC_URL=https://altero.example.org
EOF

docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml config | grep ALTERO_    # what it will use
```

That last line is worth running. Compose resolves the file and prints the
settled values, so a variable that did not arrive is visible before a user is
waiting on a confirmation rather than after.

Four things go wrong here, all quietly:

- **`docker/.env`, not `./.env`.** Compose reads `.env` from the directory
  holding the compose file, which is *not* the directory the documented
  commands are run from. A `.env` at the repository root is read by nothing and
  changes nothing.
- **A `$` in a password is eaten.** Compose interpolates `.env` values, so
  `s3cret$foo` arrives as `s3cret` — with a warning that names `foo` as an
  unset variable, which reads like someone else's problem. Double it: `$$`.
  That is on top of the percent-encoding the URL needs, so a password of
  `p@ss$1` is written `p%40ss$$1`.
- **`localhost` is the container.** A relay on the Docker host is
  `smtp://host.docker.internal:25` — the compose file maps that name to the
  host gateway for this reason. `localhost` inside the container reaches the
  container itself, and a relay bound to `127.0.0.1` on the host is not
  reachable from a container at all until it also listens on the bridge.
- **`ALTERO_PUBLIC_URL` is not optional here.** The API is published on the
  loopback interface for a TLS terminator to sit in front of, so the address a
  request arrives on is the terminator's idea of it. Without this the
  confirmation link points at something internal.

`ALTERO_MAIL_FROM` is best kept a bare address. A display name is allowed, but
`.env` has no quoting to speak of and the value is taken literally to the end
of the line, so `altero <altero@example.org>` works while a stray quote becomes
part of the address.

With `ALTERO_SMTP_URL` unset or empty — the default — messages go to the log,
and that is a supported way to run:

```sh
docker compose -f docker/compose.yaml logs altero | grep -A8 'was not sent'
```

That is how the owner of a fresh container reads their own confirmation link.

## Group notifications

A shared library that nobody watches is one where a paper somebody added sits
unread for a month. This is the answer to that, and it is the one thing altero
sends that the recipient did not personally cause.

**Nobody is subscribed to anything.** Every member of every group starts with
all four switches off, including on an upgrade of an instance that already has
groups. Turning one on is done in the browser, in the group's own panel, and it
is per group and per kind:

| Switch | What counts |
| --- | --- |
| Items added or changed | Anything written to an item, including a title fixed |
| Items deleted | Trashed as well as removed outright — trashing is what people mean |
| People joining or leaving | Membership changes |
| Collections added or changed | The library's structure |

It is your own subscription and nobody else's. A group's administrator decides
who may read and write, not what anybody is mailed about.

### Why it waits

A syncing client uploads in batches of fifty. Sending on each write would mail
every member ten times for one sync of a five-hundred-item library, which is
how a notification becomes something people filter away.

So activity is recorded as it happens and delivered only once the library has
stopped changing. A background sweep looks for group libraries whose newest
unsent activity is older than the quiet period, and renders everything waiting
as one message:

```
Subject: New activity in “Kollaps”

Since you were last told, in the group library “Kollaps”:

12 items were added or changed
1 item was deleted
```

Two settings control it, and both may be left alone:

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `GROUP_DIGEST_QUIET_PERIOD` | `ALTERO_GROUP_DIGEST_QUIET_PERIOD` | `900` | Seconds a library must be quiet before what happened in it is sent |
| `GROUP_DIGEST_INTERVAL` | `ALTERO_GROUP_DIGEST_INTERVAL` | `60` | Seconds between sweeps. **`0` turns group notifications off entirely** |

Raising the quiet period makes messages rarer and later. Lowering it toward
zero approaches one message per write, which is the thing it exists to prevent.

### What it does not do

**It does not tell you what you did.** Activity is attributed, and the person
who caused a change is excluded from the digest about it — per change, so when
two people have been working each hears what the other did and neither is told
about their own afternoon.

**It does not say what changed.** The counts are counts: twelve items, not
which twelve. Naming them would mean a message that leaks the contents of a
library into an inbox and a mail server's logs, and the library is one click
away for anybody who received the message.

**It is not a queue.** This is still true of the whole module: nothing is
retried. A relay that refuses a digest produces a line in the log and the
activity is marked delivered anyway, because the alternative is sending the
same digest to everybody again on the next sweep. The in-app notification is
raised whether or not the mail goes, so nothing is lost that mattered.

**It does not need one process.** Unlike the streaming API, whose broker is in
memory, this survives being run several times over: the sweep claims what it is
about to send in the database, so two workers cannot mail the same digest
twice. `test_concurrency.py` runs three sweeps at once against PostgreSQL and
asserts that exactly one message goes.

**A member with no address still hears about it.** The notification appears in
the interface regardless; the mail is the copy. That is the same reasoning as
everywhere else here — an instance may have no relay at all.

## Checking that it works

There is no test command. The shortest real exercise is the confirmation
message, which any signed-in account can ask for again:

1. Sign in to `/app` with an account whose address is unconfirmed. A notice sits
   across the top of the interface with a **Resend** on it. The endpoint answers
   `202` whether or not anything was sent — reporting delivery would tell a
   caller whether an address is already confirmed — so the answer is not the
   evidence.
2. Read the log. A relay that refused the message logs `Could not send mail to
   <address>: <reason>` at `ERROR`, with the relay's own words for why.
3. Read the inbox. Delivery accepted by a relay is not delivery to a person.

To watch the SMTP conversation instead of sending anything real, point altero at
a local sink:

```sh
uvx --from aiosmtpd python -m aiosmtpd -n -l localhost:8025   # prints what it receives
ALTERO_SMTP_URL=smtp://localhost:8025 uv run altero
```

It offers no `STARTTLS`, so this is also the path that logs `localhost does not
offer STARTTLS; sending in the clear` — useful for confirming that warning is
one you are seeing on purpose rather than against a real relay.

## When sending fails

Nothing in this module raises. Every message is *about* something that has
already happened — an address to confirm, a password that has changed — so
failing the request that caused it would undo nothing and lose the change
instead. A dead relay does not turn a password change into a `500`; it produces
a line in the log and a password that is changed.

The consequence is that failures are only visible in the log. There is no queue
and no retry: a message the relay would not take is gone, and the way to get
another is to ask for another — resend the confirmation, send the invitation
again. For the volume altero sends, a queue would be more machinery to keep
working than the thing it protects.

Sending happens on a worker thread with a 10-second timeout, so a slow relay
holds one request for at most that long and never blocks the event loop.

## Related

- [deployment.md](deployment.md) — configuration, reverse proxies, containers
- [web-interface.md](web-interface.md#accounts) — who may register, and how
  invitations reach somebody without an account
- [administration.md](administration.md) — accounts and passwords from the
  command line
