# OpenID provider interoperability

Historical local assessment on **2026-10-31**, using altero at `d06783c`:
the OpenID Foundation suite's **Config OP passed**. **Basic OP did not pass**.
This is a development assessment, not OpenID certification or an exhaustive
claim of protocol support. The mandatory S256 PKCE policy was retained.

## Independent client in CI

Run the independent Authlib client checks with:

```sh
uv run pytest -q tests/test_authlib.py
```

They cover code and PKCE, public/confidential clients, ID tokens, userinfo,
refresh, replay, revocation, device consent and logout over live HTTP. No
external provider is required. Keep loopback port 18765 free.

The harness approves through real cookie/CSRF routes, without testing consent
page rendering or a separate client callback listener. See the
[fixture scope](https://github.com/eseifert/altero/blob/master/tests/idp/README.md).

### Recorded CI run

On 2026-10-31, the [hosted job at `fcf8460`](https://github.com/eseifert/altero/actions/runs/41250704073/job/124683435185)
passed 3,556 tests without skips, including 24 Authlib cases using Authlib 1.9.1.
The same job ran Keycloak and SimpleSAMLphp tests. Local token mutations made
Authlib reject changed nonce and access-token hashes after intact baselines
passed. These results are separate from the Foundation assessment below.

## Foundation suite environment

The official [conformance suite](https://openid.net/certification/about-conformance-suite/)
reported version **5.3.4**, tag `release-v5.3.4`, revision `e8d5167`.
The reviewed source checkout was
[`e8d5167c84f1913a137c260f7ee991f03908ce8f`](https://gitlab.com/openid/conformance-suite/-/tree/e8d5167c84f1913a137c260f7ee991f03908ce8f).
The downloaded images were pinned by digest:

```text
registry.gitlab.com/openid/conformance-suite@sha256:74fe707b772ca48f0be0762027eabf89de463367770e3f9318c6b7c1cbbbbcef
mongo@sha256:b9924c330a8bbc5800fe9c69f04a84e221eca7b28fd049a0354147d9908fa142
```

MongoDB belongs to the suite and stores its plans and results. altero used
SQLite; it gained no MongoDB dependency. Both containers were disposable and
bound only to loopback, with MongoDB on 27174 and the suite on HTTPS 18084.
The suite ran its development profile with its dummy local administrator.
This configuration is for isolated testing, never a public deployment.

altero served HTTPS on 18766 with `public_url=https://127.0.0.1:18766` and a
fresh test account. A short-lived local certificate covered `127.0.0.1` and
`localhost`; the suite's Java trust store and the httpx2 driver trusted it.
Chromium accepted this local certificate when executing the suite's callback
JavaScript and capturing its requested error-page screenshots. No production
accounts, identity providers or library databases were used.

## Profile results

| Profile | Passed | Failed | Warning | Review | Skipped |
|---|---:|---:|---:|---:|---:|
| Config OP (1 module) | 1 | 0 | 0 | 0 | 0 |
| Basic OP (35 modules) | 2 | 27 | 1 | 2 | 3 |

The retained local plans are `kdzACvYOP0Vjk` (Config) and `qi0Q55XJAGHiD`
(Basic), with per-module logs and complete JSON exports.

All modules were invoked. These are the suite's results, including its skips
and review requirements; they are not converted into passes. It commonly
records an asserted protocol failure with status `INTERRUPTED` and result
`FAILED`.

The 27 failed Basic modules reached authorization without a PKCE challenge.
altero returned `invalid_request` with `code_challenge is required`. That
prevents the later checks named by those modules from running: this assessment
does not establish their userinfo, refresh, prompt, locale or code-reuse
behavior. The explicit valid-PKCE module completed the code flow successfully,
including the suite's token and identity checks. The independent Authlib cases
separately exercise supported flows with PKCE.

The missing-response-type module reported `PASSED` on that same missing-PKCE
error. This does **not** prove a correct missing-response-type check: altero
currently defaults an omitted response type to `code`. The authorization POST
module received 405 and reported `WARNING` after its 30-second callback wait.
The address, phone and all-scopes modules were skipped by the suite because
the required scopes were not advertised. Two unregistered-redirect cases
displayed the expected local error; actual Chromium screenshots were uploaded
and inspected, and their suite result remains `REVIEW`.

For Basic OP, every module name below has the prefix `oidcc-`:

| Module | Result |
|---|---|
| `server` | FAILED |
| `response-type-missing` | PASSED (limited as explained above) |
| `userinfo-get` | FAILED |
| `userinfo-post-header` | FAILED |
| `userinfo-post-body` | FAILED |
| `ensure-request-without-nonce-succeeds-for-code-flow` | FAILED |
| `scope-profile` | FAILED |
| `scope-email` | FAILED |
| `scope-address` | SKIPPED |
| `scope-phone` | SKIPPED |
| `scope-all` | SKIPPED |
| `alternate-happy-flow` | FAILED |
| `display-page` | FAILED |
| `display-popup` | FAILED |
| `prompt-login` | FAILED |
| `prompt-none-not-logged-in` | FAILED |
| `prompt-none-logged-in` | FAILED |
| `max-age-1` | FAILED |
| `max-age-10000` | FAILED |
| `ensure-request-with-unknown-parameter-succeeds` | FAILED |
| `id-token-hint` | FAILED |
| `login-hint` | FAILED |
| `ui-locales` | FAILED |
| `claims-locales` | FAILED |
| `ensure-request-with-acr-values-succeeds` | FAILED |
| `codereuse` | FAILED |
| `codereuse-30seconds` | FAILED |
| `ensure-registered-redirect-uri` | REVIEW |
| `ensure-post-request-succeeds` | WARNING |
| `server-client-secret-post` | FAILED |
| `unsigned-request-object-supported-correctly-or-rejected-as-unsupported` | FAILED |
| `claims-essential` | FAILED |
| `ensure-request-object-with-redirect-uri` | REVIEW |
| `refresh-token` | FAILED |
| `ensure-request-with-valid-pkce-succeeds` | PASSED |

Config OP's `oidcc-discovery-endpoint-verification` passed without warnings.
It checked discovery, required metadata, JWKS and HTTPS endpoint URLs; it does
not execute a sign-in or certify the TLS configuration of a public deployment.

## Repeating the assessment

Use the official suite's
[local Docker instructions](https://gitlab.com/openid/conformance-suite/-/blob/e8d5167c84f1913a137c260f7ee991f03908ce8f/docker-compose-prebuilt.yml)
with the pinned image above and an isolated database. Configure HTTPS for the
suite and altero, trust the test CA in Java, and set altero's public URL to its
actual issuer. Register two confidential clients through `altero oauth add`,
both with scopes `openid profile email` and the suite's exact callback:
`https://127.0.0.1:18084/test/a/altero/callback` for alias `altero` in this run.

In the suite configuration, set `server.discoveryUrl` to altero's discovery
URL. Supply `client` and `client2` objects with their respective `client_id`,
`client_secret` and `scope`. Also supply `client_secret_post` with the first
client's values: the Basic plan uses that separate object for its form-secret
module. An absent object is a setup failure, not protocol evidence.

Run `oidcc-config-certification-test-plan` with its fixed defaults. Run
`oidcc-basic-certification-test-plan` with `server_metadata=discovery` and
`client_registration=static_client`; the plan fixes response type, mode and
authentication method per module. Follow its actual authorization URLs,
authenticate the disposable account, approve consent where offered, and run
the suite's callback JavaScript. Upload the requested real error screenshots.
Do not insert PKCE into the suite's requests or relax altero's PKCE requirement
to turn this profile green.

Retain raw plans, per-module logs and screenshots privately: suite exports
contain client secrets, session cookies and tokens. Publish only sanitized
results. The local assessment retained these under `/tmp/altero-p74-oidf`;
the containers and live server were stopped afterwards. The hosted Authlib
result is linked above; the Foundation assessment itself remains a local run.
