# Connecting other applications

Operators can register applications that need limited access to an altero
library. Users approve each application in their browser and can disconnect
it later. The application receives expiring tokens instead of a password or
long-lived API key.

This is separate from [institutional sign-in](administration.md#sign-in-providers).
Zotero Desktop still uses an API key; browser sessions never authenticate the
Zotero API.

## Registering an application

Set `ALTERO_PUBLIC_URL` to the stable external HTTPS address first. Register the
application from the server shell:

```sh
uv run altero oauth add notebook \
    --name "Notebook" \
    --description "Reads your library into a notebook" \
    --redirect-uri https://notebook.example.com/auth/callback \
    --scope openid --scope profile --scope library.read --scope files.read
```

Repeat `--redirect-uri` and `--scope` as needed. The registered scopes are a
ceiling: the application can request these or fewer. Applications cannot
register themselves.

For a server application that can protect a secret, add `--confidential`.
Copy the secret when it is printed; it cannot be shown again.
For logout redirects, register each address with `--post-logout-redirect-uri`.

```sh
uv run altero oauth list
uv run altero oauth disable notebook
uv run altero oauth rotate-key
```

Disabling stops the application for everyone. Key rotation changes the key
used to sign new ID tokens while retaining verification keys for older tokens.

### Redirect URIs

Use absolute URIs without fragments. HTTPS is required except for loopback
addresses and native-app private schemes such as `com.example.app:/callback`.
Matching is exact, including path and query.

For a native app's loopback callback, the port may vary: registering
`http://127.0.0.1:1/callback` permits another port at that same host and path.
`localhost` and `[::1]` have the same exception.

## What an application gets

Access tokens last one hour; refresh tokens last thirty days. Send an access
token with each API request:

```http
GET /users/1/items HTTP/1.1
Authorization: Bearer alt_at_…
```

| Scope | Permission |
| --- | --- |
| `openid` | Identify the account; no library access |
| `profile` | Read its display name and username |
| `email` | Read its email address and confirmation status |
| `groups` | Read group names; no group-library contents |
| `library.read` | Read personal-library items, collections, searches and tags |
| `library.write` | Add, change and remove personal-library objects |
| `notes.read` | Include notes in readable libraries |
| `files.read` | Download attachment bytes |
| `groups.read` | Read group libraries the account belongs to |
| `groups.write` | Write to those group libraries |

`library.write` requires `library.read`; `groups.write` requires `groups.read`.
`notes.read` and `files.read` require `library.read`. Unknown, unregistered or
incomplete scope combinations are refused.

Notes without permission disappear from listings and direct reads. Without
file permission, attachment metadata and extracted full text remain readable,
but file downloads are refused. Public-library note access has an exception;
see [credential restrictions](compatibility.md#a-credential-that-gave-up-notes-or-files).
Group policies and member restrictions continue to apply to tokens.

## Where a grant reaches

On the consent screen, the user can allow all resources covered by the scopes
or select particular libraries and collections. Applications cannot choose or
widen that selection.

A collection grant includes its subcollections and items filed there later,
plus child notes, attachments and annotations. It does not include unfiled
items or objects filed only elsewhere. Restricted collection grants cannot
read saved searches, settings or deletion logs, or change library structure.
Items inside the grant remain writable when scopes permit; new items must
be filed within it.

Restrictions persist when tokens are refreshed. Approving again replaces the
grant rather than accumulating access. Deleting its last selected collection
does not turn a restricted grant into unrestricted access. API keys are unaffected.
See [resource restrictions](compatibility.md#confining-a-grant-to-particular-resources)
for endpoint behavior.

## The flow

The following sections are for application developers. Use discovery and an
OAuth/OpenID client library where possible. Authorization code requires PKCE
with `S256` for every client, including confidential clients.

1. Generate a verifier, its challenge, and a random `state` value.
2. Open the authorization endpoint in the user's browser:

   ```text
   /oauth/authorize
     ?client_id=notebook
     &redirect_uri=https://notebook.example.com/auth/callback
     &response_type=code
     &scope=openid%20profile%20library.read
     &state=<random-value>
     &code_challenge=<BASE64URL(SHA256(verifier))>
     &code_challenge_method=S256
     &nonce=<optional-nonce>
   ```

3. The user signs in and reviews consent in altero. At the callback, verify `state` before exchanging the code.
4. Exchange the code on the back channel:

   ```sh
   curl -X POST https://library.example.org/oauth/token \
     -d grant_type=authorization_code \
     -d client_id=notebook \
     -d code=... \
     -d code_verifier=... \
     -d redirect_uri=https://notebook.example.com/auth/callback
   ```

The response contains `access_token`, `token_type`, `expires_in`, `refresh_token`
and `scope`, plus an `id_token` when `openid` was granted.

### Presenting a client secret

Public clients send no secret. Confidential clients authenticate every token
request using HTTP Basic or a `client_secret` form field. Never send the secret
both ways in one request. If Basic and a form `client_id` are both present,
they must identify the same client.

Discovery advertises `none`, `client_secret_basic` and `client_secret_post`.

### Refresh and replay

```sh
curl -X POST https://library.example.org/oauth/token \
  -d grant_type=refresh_token -d client_id=notebook -d refresh_token=alt_rt_...
```

Confidential clients also supply their secret. Replace the saved refresh token
after each successful refresh. Reusing a spent refresh token or authorization
code revokes the token family, including when concurrent requests race.
The application must start authorization again.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `/.well-known/openid-configuration` | OpenID discovery |
| `/.well-known/oauth-authorization-server` | OAuth discovery |
| `/oauth/authorize` | Browser authorization |
| `/oauth/token` | Code exchange, refresh and device polling |
| `/oauth/revoke` | Token revocation |
| `/oauth/userinfo` | Claims allowed by the scopes |
| `/oauth/jwks.json` | ID-token verification keys |
| `/oauth/logout` | End the browser session |
| `/oauth/device_authorization` | Start authorization on a device without a browser |

Revocation uses the same client authentication methods as the token endpoint.
Revoking an access token leaves its refresh token usable; revoking a refresh
token invalidates its family. Unknown tokens receive a successful response;
clients cannot revoke another application's tokens.

## A device with no browser

Post `client_id` and `scope` to `/oauth/device_authorization`. Show the returned
`user_code` and `verification_uri`, or open `verification_uri_complete` on
another device. Keep `device_code` private.

Poll `/oauth/token` with:

```text
grant_type=urn:ietf:params:oauth:grant-type:device_code
&client_id=notebook&device_code=...
```

Respect the returned `interval`. Device codes expire after ten minutes.

| Response | Action |
| --- | --- |
| `authorization_pending` | Continue polling at the allowed interval |
| `slow_down` | Increase the interval |
| `access_denied` | Stop; the user refused |
| `expired_token` | Stop and start a new request if needed |
| Tokens | Save them; the device code is spent |

Confidential clients authenticate while polling. Device authorization uses no
PKCE or redirect, but registration still requires a redirect URI. The first
completed consent decision stands.

## Signing out

Send the browser to `/oauth/logout` using GET or POST with a required
`id_token_hint`. An optional `post_logout_redirect_uri` must match a registered
logout address; `state` is returned there.

The hint must be a token altero signed for the signed-in account. An expired
hint is accepted. Logout ends the browser session but leaves the application's
grant and tokens usable. To withdraw access, disconnect the application in
Settings or revoke its tokens.

## ID tokens

Tokens use RS256. Verify them with `/oauth/jwks.json` and the issuer from
discovery. Claims include `iss`, `sub`, `aud`, `iat`, `exp`, `auth_time` and
`at_hash`, plus a requested `nonce` and granted identity claims.

Use `sub` as the stable account identifier. Email and group names are not
identifiers; group names are not unique. The `groups` claim is an empty list
when no groups apply. Resource restrictions also narrow that list.

The issuer comes only from `ALTERO_PUBLIC_URL`. These endpoints refuse to
operate without it. Signing keys persist in the database.

## What a person sees

The consent page names the application, explains its permissions, highlights
new permissions, and offers library or collection restrictions. Users sign in
through their usual password, passkey or institutional provider first.

**Settings → Connected applications** shows permissions and restrictions.
Disconnecting revokes access immediately.

## Interoperability checks

Authlib exercises live flows in CI. The recorded OpenID Foundation assessment
passed Config OP but did not pass Basic OP, partly because it omits the PKCE
challenge altero requires. altero is not OpenID-certified. Read the
[results and limits](oidc-conformance.md) before depending on an OpenID feature.

## Security notes

Tokens never bypass the account's own permissions. Suspension stops token access
along with other credentials. `/keys/current` and key-management routes refuse
access tokens; use grant disconnection or token revocation instead.

Credentials and codes are stored as hashes. Expired authorization records are
removed by the retention sweep. See the [compatibility decisions](compatibility.md#the-authorization-server)
for the authentication boundary and deliberate protocol choices.
