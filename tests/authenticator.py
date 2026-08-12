"""A software authenticator, so passkey ceremonies can be driven for real.

Produces genuine WebAuthn structures -- CBOR attestation objects, real ES256
signatures over the authenticator data and client data hash -- so the tests
exercise the `webauthn` library's verification rather than a stub of it. Only
the hardware is simulated.

Kept out of one test module because both the service tests and the route tests
want it.
"""

import base64
import json
import struct
from hashlib import sha256

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

#: Flags in authenticator data: user present, user verified, attested
#: credential data included, backup eligible, backed up.
UP = 0x01
UV = 0x04
BE = 0x08
BS = 0x10
AT = 0x40


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class Authenticator:
    """One device holding one passkey."""

    def __init__(
        self,
        *,
        credential_id: bytes = b"a-credential-id-0123",
        backed_up: bool = True,
        verifies_user: bool = True,
    ):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = credential_id
        self.sign_count = 0
        self.backed_up = backed_up
        # False models a key that only checks somebody touched it -- an old
        # U2F token, or a passkey used without a PIN. altero requires more.
        self.verifies_user = verifies_user

    def _cose_key(self) -> bytes:
        """The public key, as COSE wants it: EC2, P-256, ES256."""
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps(
            {
                1: 2,  # kty: EC2
                3: -7,  # alg: ES256
                -1: 1,  # crv: P-256
                -2: numbers.x.to_bytes(32, "big"),
                -3: numbers.y.to_bytes(32, "big"),
            }
        )

    def _authenticator_data(self, rp_id: str, *, attested: bool) -> bytes:
        flags = UP
        if self.verifies_user:
            flags |= UV
        if self.backed_up:
            flags |= BE | BS
        if attested:
            flags |= AT

        data = sha256(rp_id.encode()).digest() + bytes([flags])
        data += struct.pack(">I", self.sign_count)

        if attested:
            key = self._cose_key()
            data += (
                b"\x00" * 16  # AAGUID
                + struct.pack(">H", len(self.credential_id))
                + self.credential_id
                + key
            )
        return data

    def _client_data(self, kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps(
            {"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}
        ).encode()

    def register(self, options: dict, *, origin: str, rp_id: str) -> dict:
        """Answer a creation ceremony, as `navigator.credentials.create` would."""
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        authenticator_data = self._authenticator_data(rp_id, attested=True)

        # "none" attestation: no attestation statement to verify, which is what
        # altero asks for and what every consumer authenticator sends.
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": authenticator_data})

        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "attestationObject": b64(attestation),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
        }

    def authenticate(self, options: dict, *, origin: str, rp_id: str, advance: bool = True) -> dict:
        """Answer a request ceremony, as `navigator.credentials.get` would."""
        if advance:
            self.sign_count += 1

        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        authenticator_data = self._authenticator_data(rp_id, attested=False)

        signature = self.key.sign(
            authenticator_data + sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )

        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "authenticatorData": b64(authenticator_data),
                "signature": b64(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }

    def authenticate_with_a_broken_signature(
        self, options: dict, *, origin: str, rp_id: str
    ) -> dict:
        """The same, with the signature mangled but still well-formed.

        Flipping a byte would frequently produce something that is not a valid
        DER signature at all, and be refused for the wrong reason; this
        re-encodes a genuinely different (r, s) so what fails is the check.
        """
        answer = self.authenticate(options, origin=origin, rp_id=rp_id)
        r, s = decode_dss_signature(unb64(answer["response"]["signature"]))
        answer["response"]["signature"] = b64(encode_dss_signature(r ^ 1, s))
        return answer
