"""Signing JSON Web Signatures, and publishing the key that verifies them.

This module signs, and verifies only what it signed itself. ``docs/compatibility.md``
records at length why altero does not verify the signature on an ID token it
*receives*: verification is where JWS goes wrong -- ``alg: none``,
HMAC-versus-RSA confusion, a key chosen by an attacker-supplied ``kid``, a JWKS
fetch that is itself a request to get right -- and every one of those is a
decision made about input somebody else controls.

Signing has none of them. The algorithm is fixed at RS256, the key is this
server's own, and nothing here reads a header to decide anything. What is left
is RFC 7515's compact serialisation, which is two base64url segments, a
signature over them, and a third: small enough to hold against the
specification's own test vector, which ``tests/test_jws.py`` does with RFC 7515
Appendix A.2. That is the same bargain ``services/totp.py`` takes with RFC 6238
-- a published vector is what makes hand-writing one of these defensible, and
the absence of one is why ``services/saml.py`` does not hand-write its
signatures.

:func:`verify` has none of them either, and that is the reason it is allowed to
exist beside the decision not to verify somebody else's token. It is handed the
keys, so a ``kid`` selects among *this server's* and nothing else and there is
no fetch; the algorithm is compared against RS256 rather than read out of the
header; and a token that fails any check raises. The only thing it is used for
is the ``id_token_hint`` on the logout endpoint -- a token this server signed,
coming back.

RS256 rather than ES256 because OpenID Connect Core makes it the algorithm
every client must support, and because PKCS#1 v1.5 is deterministic: the same
key and payload produce the same signature every time, so Appendix A.2 can be
reproduced rather than merely accepted.
"""

import base64
import hashlib
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

#: The one algorithm this server signs with. Not a parameter: an algorithm
#: chosen per call is the seam every JWS confusion attack goes through, and a
#: provider has no reason to offer a choice it does not need.
ALGORITHM = "RS256"

#: Modulus size for a newly generated key. 2048 is the floor RFC 7518 sets for
#: RS256 and what every client is prepared to verify.
KEY_SIZE = 2048


def b64url(raw: bytes) -> str:
    """Return ``raw`` base64url-encoded without padding, as JOSE writes it."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def generate_private_key() -> str:
    """Return a fresh RSA private key as a PKCS#8 PEM string."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def load_private_key(pem: str) -> rsa.RSAPrivateKey:
    """Return the key ``pem`` holds, refusing anything that is not RSA."""
    key = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):  # pragma: no cover - not reachable today
        raise ValueError("Only RSA keys can sign an RS256 token")
    return key


def _int_to_b64url(value: int) -> str:
    """Return an integer as the base64url big-endian octet string JWK wants."""
    width = (value.bit_length() + 7) // 8
    return b64url(value.to_bytes(width, "big"))


def public_jwk(pem: str, kid: str) -> dict[str, str]:
    """Return the public half of ``pem`` as a JWK, as ``/oauth/jwks.json`` serves it."""
    numbers = load_private_key(pem).public_key().public_numbers()
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": ALGORITHM,
        "kid": kid,
        "n": _int_to_b64url(numbers.n),
        "e": _int_to_b64url(numbers.e),
    }


def jwk_thumbprint(n: str, e: str) -> str:
    """Return the RFC 7638 thumbprint of the RSA public key ``(n, e)`` describes.

    RFC 7638 fixes both the member set and their order: for RSA it is exactly
    ``e``, ``kty`` and ``n``, lexicographically, with no whitespace. Taking the
    encoded components rather than a key object is what lets
    ``tests/test_jws.py`` hold this against §3.1's worked example, which prints
    a public key and the thumbprint that must come out of it.
    """
    canonical = json.dumps({"e": e, "kty": "RSA", "n": n}, separators=(",", ":"), sort_keys=True)
    return b64url(hashlib.sha256(canonical.encode("ascii")).digest())


def thumbprint(pem: str) -> str:
    """Return the RFC 7638 thumbprint of ``pem``'s public half, used as the ``kid``.

    Derived from the key rather than assigned, so the same key always names
    itself the same way -- a client that cached a JWKS and looks a ``kid`` up in
    it finds the key it already has, and two servers restoring the same backup
    do not disagree about what to call it.
    """
    numbers = load_private_key(pem).public_key().public_numbers()
    return jwk_thumbprint(_int_to_b64url(numbers.n), _int_to_b64url(numbers.e))


def sign(payload: dict[str, Any], pem: str, kid: str) -> str:
    """Return ``payload`` as a signed JWT in compact serialisation.

    ``typ`` is set to ``JWT`` because RFC 7519 asks for it where a JOSE object
    could be confused for another kind, and an ID token travels next to access
    tokens that are not JWTs at all.
    """
    header = {"alg": ALGORITHM, "typ": "JWT", "kid": kid}
    segments = [
        b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")),
        b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = load_private_key(pem).sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{'.'.join(segments)}.{b64url(signature)}"


def sign_raw(signing_input: bytes, pem: str) -> str:
    """Return the signature over ``signing_input``, for holding against a test vector.

    RFC 7515's appendices fix the header and payload octets exactly, including
    the whitespace :func:`sign` does not emit. Reproducing a vector therefore
    means signing bytes somebody else chose, which is what this exists for.
    """
    signature = load_private_key(pem).sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return b64url(signature)


def verify(token: str, keys: dict[str, str]) -> dict[str, Any]:
    """Return the claims of a token *this server* signed, or raise ``ValueError``.

    ``keys`` maps ``kid`` to the private PEM it names, and is the whole of what
    may verify: the header selects among them and can introduce nothing. The
    algorithm is not read from the header either -- it is compared against
    RS256, so ``alg: none`` and an HMAC substituted for a signature are both
    just a token that does not verify.

    Nothing about the claims is checked here. Whether the issuer is this server,
    the audience a registered client and the subject somebody who is signed in
    is the caller's question, and keeping it there is what stops this from
    becoming a second half-authenticator.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Not a JWS in compact serialisation")

    header_segment, payload_segment, signature_segment = parts
    try:
        header = json.loads(_b64url_decode(header_segment))
        payload = json.loads(_b64url_decode(payload_segment))
        signature = _b64url_decode(signature_segment)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("This token is not readable") from exc

    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise ValueError("This token is not readable")
    if header.get("alg") != ALGORITHM:
        raise ValueError(f"Only {ALGORITHM} is signed or accepted here")

    pem = keys.get(str(header.get("kid", "")))
    if pem is None:
        raise ValueError("This token was not signed by a key this server holds")

    try:
        load_private_key(pem).public_key().verify(
            signature,
            f"{header_segment}.{payload_segment}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise ValueError("This token's signature does not hold") from exc
    return payload


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def access_token_hash(access_token: str) -> str:
    """Return the ``at_hash`` claim for ``access_token``.

    OpenID Connect Core §3.1.3.6: the left-most half of the SHA-256 of the
    token's ASCII octets, base64url-encoded. It ties an ID token to the access
    token handed out beside it, so a token substituted in transit does not go
    unnoticed by a client that checks.
    """
    digest = hashlib.sha256(access_token.encode("ascii")).digest()
    return b64url(digest[: len(digest) // 2])
