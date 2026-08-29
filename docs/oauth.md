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
| `notes.read` | Reading notes. Without it a note is not found, in every listing and by key. |
| `files.read` | Downloading attachment bytes. Without it the file routes refuse; the attachment item is still readable. |
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

`notes.read` and `files.read` are narrowings of `library.read` rather than
additions to it, and what they withhold is the object and not a field on it: a
note the token may not read does not appear in a listing and is a 404 by key,
and an attachment whose bytes the token may not have is still readable as an
item. [Compatibility notes](compatibility.md#a-credential-that-gave-up-notes-or-files)
records the whole surface, including what happens on a public library and the
two places altero deliberately differs from zotero.org.

Some scopes are useless alone and are refused rather than quietly granted.
Write access implies read access throughout altero, so `library.write` without
`library.read` would be issued and then do nothing; asking for it is an error
with a message saying so. The same holds for `groups.write`, `notes.read` and
`files.read`, each of which needs its corresponding read scope.

A scope this server does not issue — say `annotations.write` — is also refused
rather than dropped. An application asking for it has a belief about what altero
does, and handing back a token without it produces software that half works.

## Where a grant reaches

A scope says what an application may do. It does not say *where*, and by itself
`library.read` means the whole personal library while `groups.read` means every
group the account belongs to. On the consent screen the account holder can
narrow that: **only the libraries and collections I choose**.

The choice is theirs and not the application's. An application asks for scopes,
as it always did; nothing it sends can name a library or a collection, and no
parameter it adds widens what was picked. The default is unchanged — approving
without touching the choice grants everything the scopes cover, which is what
approving has always meant.

What can be picked:

- a whole library, personal or group — "group 42 and none of my others";
- one or more collections within a library, in either kind of library.

**A collection means the branch.** Choosing *Reading* also grants everything
nested inside it, at any depth, and everything filed there later. That is the
reading altero already gives a named collection: a [shared
collection](web-interface.md) means the branch, and so does the desktop client's
*Show Items from Subcollections*. The alternative would mean somebody who files
a paper into a subcollection quietly withdraws it from an application they
granted the parent to.

What a collection grant reaches, exactly:

- every item filed in one of the granted collections;
- their child notes, attachments and annotations — a child item is never filed
  in a collection itself, so a grant that reached only filed items would hand
  an application a paper it could not open;
- and nothing else. An unfiled item is out. An item filed only in a collection
  that was not granted is out, and so are its children.

A library that was not picked answers 403 to everything under its prefix, and
`GET /groups/<id>` answers 404 — which private groups exist is not something a
refusal should confirm. `GET /users/<id>/groups` lists only the granted group
libraries, and so does the `groups` claim. A collection that was not picked is
absent from every listing and a 404 by key, and so is an item inside one — by
key, on its children, on its file, on its full text, and on a write that names
it. Every count, key listing, version listing, search, export, full-text index
and tag count is computed over what the token can see, so none of them says that
something else is there.
[Compatibility notes](compatibility.md#confining-a-grant-to-particular-resources)
records what a narrowed grant does about the parts of a library that belong to
no collection: saved searches, settings, the delete log, writing to the
library's shape, and administering a group.

The restriction lives on the grant rather than on a token, so a **refreshed
token is the same authorization** — a restriction an application could refresh
its way out of would not be one. Approving again replaces it rather than adding
to it, so an application cannot accumulate collections by asking often, and
**Settings → Connected applications** lists what each one is limited to.

Existing grants are unaffected. A grant made before this existed is unrestricted
and stays unrestricted until somebody narrows it. So is an API key: no key can
carry a resource grant and none is changed by one.

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

`--post-logout-redirect-uri` is repeatable too, and is the separate list of
addresses somebody may be sent to after signing out — see
[Signing out](#signing-out) below. Most applications register none.

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
| `/oauth/logout` | RP-initiated logout, as OpenID Connect names `end_session_endpoint` |
| `/oauth/device_authorization` | Where a device with no browser starts, RFC 8628 |

## A device with no browser

A machine that cannot show a browser — a terminal on a server, a reader, a box
plugged into a television — asks here instead:

```http
POST /oauth/device_authorization
client_id=notebook&scope=openid%20library.read
```

and is handed a long `device_code` it keeps, a short `user_code` it shows, the
`verification_uri` to show beside it, an `expires_in` of ten minutes and the
`interval` in seconds at which it may poll. Somebody types the short code into
that address — or follows `verification_uri_complete`, which carries it — and is
shown **the same consent screen every other application gets**. A second consent
screen written for devices would be a second place for the two to disagree about
what is being granted.

Meanwhile the device polls the token endpoint:

```http
POST /oauth/token
grant_type=urn:ietf:params:oauth:grant-type:device_code
&client_id=notebook&device_code=…
```

Four of the five answers are errors, and they are different errors on purpose:

| Answer | What the device does |
| --- | --- |
| `authorization_pending` | Keep asking. Nobody has answered yet. |
| `slow_down` | Keep asking, less often. It polled inside the interval. |
| `access_denied` | Stop. Somebody said no. |
| `expired_token` | Stop. The code lived ten minutes and nobody answered. |
| the tokens | Done, and the device code is spent. |

There is no redirect URI and no PKCE here, because there is nothing for either
to bind to: no authorization code travels through a browser. What takes their
place is the device code, which is long, random and known only to the device
that asked for it. The user code is eight characters of a twenty-consonant
alphabet — no vowels, so no code is a word anybody would rather read out, and
none of `0`/`O`, `1`/`I` or `5`/`S` to mistype — which is about 34 bits for a
code that lives ten minutes. Case and the dash are decoration: `wdjb mjht` is
the same code as `WDJB-MJHT`.

A confidential client still presents its secret when it polls. Registration is
the same `altero oauth add`, and a client needs a redirect URI registered even
if it only ever uses this flow — the two are not exclusive.

## Signing out

An application can send somebody here to end their altero browser session:

```
GET /oauth/logout
      ?id_token_hint=eyJhbGciOiJSUzI1NiIs…
      &post_logout_redirect_uri=https://notebook.example.com/signed-out
      &state=opaque
```

`POST` works the same way. Three things about it are decided rather than
defaulted:

**`id_token_hint` is required**, where OpenID Connect RP-Initiated Logout 1.0
only recommends it. This endpoint is a navigation, so any page on the internet
can send a browser to it; without something the caller could only have received
from this server, a hidden image on somebody else's site would sign people out
of their library all day. An ID token is that thing — it was handed to an
application at the token endpoint, over TLS.

Its signature is checked against altero's own keys and its issuer against
altero's own name. Its **expiry is not checked**: an ID token lives an hour and
somebody signs out whenever they decide to. If its `sub` is not the account the
browser is signed in as, nothing is ended — an application holding a stale token
for one person does not sign out whoever is at the browser now.

**`post_logout_redirect_uri` must be registered**, exactly, for the client the
ID token was issued to. An unregistered address is refused *on this server* and
not redirected to, the same rule the authorization endpoint follows: bouncing
anything off an unverified address is how an open redirector is built. With no
address given, the browser lands on the interface.

**The session ends; the grant does not.** The application keeps the tokens it
was issued, because signing out of a browser is not withdrawing consent. Taking
an application's access away is **Settings → Connected applications**, or
`/oauth/revoke` for one token.

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

Below that it asks **where** the application may reach, when the scopes reach a
library at all: everything the permissions cover, which is the default, or only
the libraries and collections the person ticks. The collections are drawn as a
tree, since choosing one grants the branch under it. Turning the choice on and
ticking nothing is refused rather than treated as everything. Where a standing
grant is already narrowed, the screen says what it is narrowed to.

Every application somebody has connected is listed under **Settings → Connected
applications**, with what it may do, where it may reach, and whether it is
currently in use. Disconnecting one takes effect immediately: the tokens go with
the grant rather than running out an hour later.

## Security notes

- The v3 API accepts an access token *in addition to* an API key. It never
  accepts a browser cookie; see
  [the boundary](compatibility.md#a-second-credential-for-the-v3-api).
- A resource grant only ever narrows. It is applied in `access_for` beside the
  four ceilings already there — the credential's grants, group membership, the
  group's policy, the member's own permission — so it can never let a token
  reach something its owner could not, and a library its owner is not a member
  of cannot be picked in the first place.
- `/keys/current` and `/keys/{key}` refuse an access token. They are about an
  API key as an object, and a token is not one — what a person revokes is the
  application.
- A suspended account stops both credentials at once, in
  `services/auth.authenticate` and in `services/websessions.lookup`.
- Access tokens and refresh tokens are stored only as SHA-256 hashes, as
  authorization codes are.
- Expired requests, codes and tokens are swept by
  `altero retention run` along with everything else that carries its own expiry.
