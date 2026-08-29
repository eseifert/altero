# Connecting other applications

altero can act as an OAuth 2.0 authorization server and OpenID Connect provider,
so that a third-party application — a reading tool, an editor plugin, a script,
a mobile app — can be given access to somebody's library without ever being
handed their password or a long-lived API key.

> [!IMPORTANT]
> This does not change how the Zotero desktop client connects. A desktop client
> still takes an API key from **Settings → API keys**, and the v3 API is still
> authenticated by a credential sent on the request and never by a browser
> cookie. What is new is a second kind of credential — a scoped, expiring access
> token — that the same v3 endpoints accept.

## What an application gets

An access token, valid for one hour, and a refresh token to replace it with.
Both are bearer credentials sent exactly the way an API key is:

```http
GET /users/1/items HTTP/1.1
Authorization: Bearer alt_at_…
```

A token carries **scopes**, and a scope grants exactly what it says:

| Scope | What it allows |
| --- | --- |
| `openid` | Establishes who the person is. Reaches no library, no item and no file. |
| `profile` | The account's name and username, through `/oauth/userinfo` and the ID token. |
| `email` | The account's email address, and whether it has been confirmed. |
| `groups` | The names of the groups the account belongs to. Reaches no library. |
| `library.read` | Reading items, collections, saved searches and tags in the personal library. |
| `library.write` | Adding, changing and removing them. |
| `notes.read` | Reading notes. |
| `files.read` | Downloading attachment bytes. |
| `groups.read` | Reading the group libraries the account belongs to. |
| `groups.write` | Writing to them. |

`groups` and `groups.read` are next to each other on the consent screen and are
not the same question. `groups` is an identity scope beside `profile` and
`email`: it says *which* groups somebody is in, by name, and reaches nothing
inside them. `groups.read` reads what is in them. An application mapping people
onto roles wants the first and should not be given the second.

The other identity scopes map onto nothing at all, and the rest map one for one
onto the permissions an API key already carries, which is what makes the mapping
checkable: a token cannot express access that a key could
not, and every ceiling that applies to a key — the group's policy, the member's
role, their own permission — applies unchanged to a token.

Some scopes are useless alone and are refused rather than quietly granted.
Write access implies read access throughout altero, so `library.write` without
`library.read` would be issued and then do nothing; asking for it is an error
with a message saying so. The same holds for `groups.write`, `notes.read` and
`files.read`, each of which needs its corresponding read scope.

A scope this server does not issue — say `annotations.write` — is also refused
rather than dropped. An application asking for it has a belief about what altero
does, and handing back a token without it produces software that half works.

## Registering an application

An operator registers it. Nothing self-registers, and there is no dynamic client
registration endpoint: the list of addresses an authorization code may be sent
to is the whole security of the flow, and a list that accepts new entries from
whoever asks is not a list.

```sh
uv run altero oauth add notebook \
    --name "Notebook" \
    --description "Reads your library into a notebook" \
    --redirect-uri https://notebook.example.com/auth/callback \
    --scope openid --scope profile --scope library.read --scope files.read
```

`--redirect-uri` is repeatable and matched **exactly**. `--scope` is repeatable
and is a ceiling: the application may ask for these or fewer, never more.

For an application that runs on a server and can keep a secret, add
`--confidential`. The secret is printed once and stored only as a hash, the same
bargain `altero key add` makes.

```sh
uv run altero oauth list                # what is registered, and what it may ask for
uv run altero oauth disable notebook    # stop it working, keeping the record
uv run altero oauth rotate-key          # sign ID tokens with a new key from now on
```

### Redirect URIs

Three rules, each of which rules out a way this is broken in the wild:

- **No fragment.** The fragment is where an implicit-flow response would go, and
  altero has no implicit flow.
- **Absolute only.** "The browser will work it out" is exactly the ambiguity
  that lets a mistake resolve somewhere unintended.
- **`https`, or the loopback interface.** The authorization code is a
  credential, and a network that can read it can spend it.

A native application that listens on an ephemeral port is the documented
exception RFC 8252 §7.3 requires: register `http://127.0.0.1:1/callback` and any
port will match, while the scheme, host, path and query still have to match
exactly. `localhost` and `[::1]` work the same way. A private-use scheme —
`com.example.app:/callback` — is accepted for a mobile application.

## The flow

Authorization code with PKCE, and **PKCE is required of every client, `S256`
only**. `plain` is neither advertised nor accepted: it makes the challenge equal
to the verifier, which is the interception PKCE exists to prevent.

```
GET /oauth/authorize
      ?client_id=notebook
      &redirect_uri=https://notebook.example.com/auth/callback
      &response_type=code
      &scope=openid%20profile%20library.read
      &state=<the application's own random value>
      &code_challenge=<BASE64URL(SHA256(verifier))>
      &code_challenge_method=S256
      &nonce=<optional, echoed into the ID token>
```

altero checks the client and the redirect URI, stores the request, and sends the
browser to its own interface at `/app/authorize`. The person signs in there the
ordinary way — with the second factor, passkey or single sign-on their account
actually has — sees what is being asked for in their own language, and answers.

The browser comes back to the registered address with `code` and `state`, and
the application exchanges the code on a back channel:

```sh
curl -X POST https://library.example.org/oauth/token \
  -d grant_type=authorization_code \
  -d client_id=notebook \
  -d code=… \
  -d code_verifier=… \
  -d redirect_uri=https://notebook.example.com/auth/callback
```

```json
{
  "access_token": "alt_at_…",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "alt_rt_…",
  "scope": "openid profile library.read",
  "id_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6…"
}
```

Refreshing rotates: the refresh token is replaced every time it is used.

```sh
curl -X POST https://library.example.org/oauth/token \
  -d grant_type=refresh_token -d client_id=notebook -d refresh_token=alt_rt_…
```

If a refresh token is ever presented *after* it was rotated away, somebody has a
copy. There is no telling which of the two callers is the thief, so every token
descended from that authorization is revoked and both have to start again. The
same happens if an authorization code is presented twice.

## Endpoints

| Endpoint | What it is |
| --- | --- |
| `/.well-known/openid-configuration` | Discovery, as OpenID Connect names it |
| `/.well-known/oauth-authorization-server` | The same document, as RFC 8414 names it |
| `/oauth/authorize` | Where the browser starts |
| `/oauth/token` | Code exchange and refresh |
| `/oauth/revoke` | RFC 7009 revocation |
| `/oauth/userinfo` | Claims the token's scopes allow |
| `/oauth/jwks.json` | The keys ID tokens are verified against |

## ID tokens

Signed with **RS256**, verifiable against `/oauth/jwks.json`. The claims are
`iss`, `sub`, `aud`, `iat`, `exp`, `auth_time` and `at_hash`, plus `nonce` when
the request carried one, and the `profile`, `email` and `groups` claims when
those scopes were granted.

`groups` is a list of group names, present and empty for an account in no group
rather than absent — an application mapping roles has to be able to tell
"belongs to nothing" from "this server did not say". Group names are **not
unique** on an altero instance, so a deployment that maps roles from them has to
keep them distinct; nothing checks that for you.

`sub` is the account's numeric id as a string. It is stable and it is the only
thing that identifies somebody: an email address is not an identity, for the
reasons `services/federation.py` sets out at length from the other side of this
protocol.

`iss` comes from `ALTERO_PUBLIC_URL` and there is **no fallback** to the address
the request arrived on. An issuer a caller can choose with a `Host` header is
not an issuer anybody can pin, so an instance without that setting refuses to
serve these endpoints rather than guessing.

Signing keys are generated on first use and kept in the database. Rotating with
`altero oauth rotate-key` starts signing with a new key and keeps publishing the
old one, so tokens issued before the rotation keep verifying until they expire.

## What a person sees

The consent screen is part of the web interface and is translated like the rest
of it. It names the application, says in sentences what it will be able to do —
"Read everything in your library", not `library.read` — and marks what is new
when an application that already has consent asks for more.

Every application somebody has connected is listed under **Settings → Connected
applications**, with what it may do and whether it is currently in use.
Disconnecting one takes effect immediately: the tokens go with the grant rather
than running out an hour later.

## Security notes

- The v3 API accepts an access token *in addition to* an API key. It never
  accepts a browser cookie; see
  [the boundary](compatibility.md#a-second-credential-for-the-v3-api).
- `/keys/current` and `/keys/{key}` refuse an access token. They are about an
  API key as an object, and a token is not one — what a person revokes is the
  application.
- A suspended account stops both credentials at once, in
  `services/auth.authenticate` and in `services/websessions.lookup`.
- Access tokens and refresh tokens are stored only as SHA-256 hashes, as
  authorization codes are.
- Expired requests, codes and tokens are swept by
  `altero retention run` along with everything else that carries its own expiry.
