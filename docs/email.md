# Email

altero can run without an SMTP relay. Configure email only if your instance needs messages delivered to users rather than written to the server log.

## Do you need a mail relay?

| Feature | Without SMTP | With SMTP |
| --- | --- | --- |
| Email confirmation | Link written to log | Delivered by email |
| Group invitations | Available in-app for existing accounts; link can be logged | Delivered by email |
| Administrator-issued password link | Link shown to administrator | Also delivered by email when possible |
| Self-service password reset | **Unavailable** | Available when enabled |
| Email second-factor code | Not useful without delivery | Delivered by email |
| Security notices | Not delivered | Delivered to confirmed addresses |
| Group activity digests | In-app notification still exists | Optional email copy |

Most messages fall back to the log when no relay is configured. Self-service password reset does **not**, because a password-setting link should not be exposed to anyone who can read server logs.

## Messages altero sends

altero sends plain-text mail for:

- confirming an email address;
- group invitations;
- password-setting links;
- email second-factor codes;
- password-change notices;
- second-factor change notices; and
- opt-in group activity digests.

Security notices are sent only to a **confirmed** email address.

Confirmation links are valid for 24 hours. Administrator-issued or self-service password links are single-use and valid for 12 hours. Email sign-in codes are valid for ten minutes, work once and are tied to the browser session that requested them.

## Run without SMTP

With `ALTERO_SMTP_URL` unset, altero logs messages at `WARNING` instead of sending them.

For Docker Compose, find a logged message with:

```sh
docker compose -f docker/compose.yaml logs altero | grep -A8 'was not sent'
```

This is a supported operating mode. An account with an unconfirmed address can still sign in, synchronize and use its library.

What you lose is external delivery: security notices, useful email-code authentication, self-service password reset and invitations to people who do not yet have an account on the instance.

## Configure an SMTP relay

Set three values:

| Setting | Environment variable | Purpose |
| --- | --- | --- |
| `SMTP_URL` | `ALTERO_SMTP_URL` | SMTP relay and optional credentials |
| `MAIL_FROM` | `ALTERO_MAIL_FROM` | Sender address |
| `PUBLIC_URL` | `ALTERO_PUBLIC_URL` | Base URL used in links |

Example:

```sh
ALTERO_SMTP_URL='smtp://altero%40example.org:s3cret@mail.example.org:587' \
ALTERO_MAIL_FROM='altero <altero@example.org>' \
ALTERO_PUBLIC_URL='https://altero.example.org' \
    uv run altero
```

Equivalent `config.py` values:

```python
SMTP_URL = "smtp://altero%40example.org:s3cret@mail.example.org:587"
MAIL_FROM = "altero <altero@example.org>"
PUBLIC_URL = "https://altero.example.org"
```

Invalid SMTP URLs are rejected when configuration is loaded, so configuration errors appear at startup rather than only when a user is waiting for mail.

## SMTP URL format

```text
smtp://[username[:password]@]host[:port]
smtps://[username[:password]@]host[:port]
```

- `smtp://` defaults to port **587** and attempts `STARTTLS`.
- `smtps://` defaults to port **465** and uses TLS from the start.

With `smtp://`, if the relay does not offer `STARTTLS`, altero logs a warning and can continue in clear text. That can be acceptable for a relay on the same trusted host or container network. Over a network you do not control, prefer `smtps://`.

### Encode credentials in the URL

Usernames and passwords are URL components. Characters such as `@`, `:`, `/`, `#`, `?` and `%` must be percent-encoded.

For example:

```text
altero@example.org  →  altero%40example.org
```

A relay that needs no authentication can omit credentials:

```python
SMTP_URL = "smtp://localhost:25"
```

## Sender address

`ALTERO_MAIL_FROM` accepts either a bare address or a display name plus address.

Use an address the relay is allowed to send as. SPF, DKIM and DMARC configuration belongs to the mail provider or relay; altero only authenticates to the relay and hands it the message.

The default `altero@localhost` is a placeholder, not a deliverable production address.

## Public URL

Set `ALTERO_PUBLIC_URL` to the external address users can open, for example:

```text
https://altero.example.org
```

This matters especially behind a reverse proxy. Without a public URL, generated links can use an internal host or port from the request that reached altero.

`ALTERO_PUBLIC_URL` is separate from `ALTERO_FORWARDED_ALLOW_IPS`: the first controls generated public links and callback addresses, while the second controls which forwarded client address altero trusts.

## Docker Compose

The Compose file already passes the mail variables through. Put them in **`docker/.env`**:

```dotenv
POSTGRES_PASSWORD=something-other-than-the-default
ALTERO_SMTP_URL=smtps://altero%40example.org:s3cret@mail.example.org
ALTERO_MAIL_FROM=altero@example.org
ALTERO_PUBLIC_URL=https://altero.example.org
```

Then restart and inspect the resolved configuration:

```sh
docker compose -f docker/compose.yaml up -d
docker compose -f docker/compose.yaml config | grep ALTERO_
```

### Common Docker mistakes

**Put the file in `docker/.env`.** The documented Compose file lives in `docker/`, and that is the environment file it reads.

**Escape `$` for Compose.** In `.env`, Compose interpolates `$NAME`. Double a literal dollar sign as `$$`. This is in addition to URL percent-encoding.

Example password `p@ss$1` inside the SMTP URL:

```text
p%40ss$$1
```

**Remember that `localhost` means the container.** A relay on the Docker host can be reached through `host.docker.internal` when the host relay is listening on an address reachable from the container network.

## Group notifications

Group activity email is opt-in. Every member starts unsubscribed.

A user can independently subscribe to these categories for each group:

| Category | Examples |
| --- | --- |
| Items added or changed | New item, title edit |
| Items deleted | Trashed or permanently removed |
| People joining or leaving | Membership changes |
| Collections added or changed | Group-library organization |

### Digest timing

Zotero uploads can contain many writes. Sending mail for every write would create a flood, so altero waits until the group has been quiet and sends one digest for the accumulated activity.

| Environment variable | Default | Meaning |
| --- | ---: | --- |
| `ALTERO_GROUP_DIGEST_QUIET_PERIOD` | `900` | Seconds the library must be quiet before a digest is ready |
| `ALTERO_GROUP_DIGEST_INTERVAL` | `60` | How often the server looks for ready digests; `0` disables delivery |

A member does not receive a digest about changes they caused themselves.

The email contains counts, not item titles. Detailed activity remains in the authenticated web interface so library contents are not unnecessarily copied into mail systems and logs.

Digest processing is coordinated in the database, so several application workers do not send the same digest twice.

There is no retry queue. If a relay refuses a digest, altero logs the failure and still keeps the in-app notification.

## Check mail delivery

The quickest real test is an email-confirmation message:

1. Sign in with an account whose address is unconfirmed.
2. Use **Resend** in the confirmation notice.
3. Check the altero log for an SMTP error.
4. Check the recipient mailbox.

A successful handoff to the SMTP relay does not guarantee delivery to the final inbox.

For a local SMTP sink:

```sh
uvx --from aiosmtpd python -m aiosmtpd -n -l localhost:8025
ALTERO_SMTP_URL=smtp://localhost:8025 uv run altero
```

This prints received messages instead of sending real mail.

## Failure behavior

Mail failure does not roll back the action that caused the message. For example, a password change remains a password change even if the security notice cannot be delivered.

Failures are logged. There is no mail queue and no automatic retry. Most user-triggered messages can be requested again.

Mail sending runs on a worker thread with a 10-second timeout so a slow relay does not block the server's event loop.

## Related

- [Deployment](deployment.md)
- [Administration](administration.md)
- [Web interface](web-interface.md)
