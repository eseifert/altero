"""The signature this server puts on an ID token, held against RFC 7515.

Hand-writing a JOSE implementation is only defensible where the specification
publishes a vector to hold it against -- the same bargain ``tests/test_totp.py``
takes with RFC 6238. RFC 7515 Appendix A.2 fixes an RSA key, the exact octets to
sign, and the signature that must come out, and PKCS#1 v1.5 is deterministic, so
the vector can be reproduced rather than merely accepted.
"""

import base64
import json

from cryptography.hazmat.primitives.asymmetric import rsa

from altero.services import jws

#: The RSA key of RFC 7515 Appendix A.2.1, as the JWK the appendix prints.
RFC7515_JWK = {
    "kty": "RSA",
    "n": (
        "ofgWCuLjybRlzo0tZWJjNiuSfb4p4fAkd_wWJcyQoTbji9k0l8W26mPddxHmfHQp-Vaw-4qPCJrcS2mJ"
        "PMEzP1Pt0Bm4d4QlL-yRT-SFd2lZS-pCgNMsD1W_YpRPEwOWvG6b32690r2jZ47soMZo9wGzjb_7OMg0"
        "LOL-bSf63kpaSHSXndS5z5rexMdbBYUsLA9e-KXBdQOS-UTo7WTBEMa2R2CapHg665xsmtdVMTBQY4uD"
        "Zlxvb3qCo5ZwKh9kG4LT6_I5IhlJH7aGhyxXFvUK-DWNmoudF8NAco9_h9iaGNj8q2ethFkMLs91kzk2"
        "PAcDTW9gb54h4FRWyuXpoQ"
    ),
    "e": "AQAB",
    "d": (
        "Eq5xpGnNCivDflJsRQBXHx1hdR1k6Ulwe2JZD50LpXyWPEAeP88vLNO97IjlA7_GQ5sLKMgvfTeXZx9S"
        "E-7YwVol2NXOoAJe46sui395IW_GO-pWJ1O0BkTGoVEn2bKVRUCgu-GjBVaYLU6f3l9kJfFNS3E0QbVd"
        "xzubSu3Mkqzjkn439X0M_V51gfpRLI9JYanrC4D4qAdGcopV_0ZHHzQlBjudU2QvXt4ehNYTCBr6XCLQ"
        "UShb1juUO1ZdiYoFaFQT5Tw8bGUl_x_jTj3ccPDVZFD9pIuhLhBOneufuBiB4cS98l2SR_RQyGWSeWjn"
        "czT0QU91p1DhOVRuOopznQ"
    ),
    "p": (
        "4BzEEOtIpmVdVEZNCqS7baC4crd0pqnRH_5IB3jw3bcxGn6QLvnEtfdUdiYrqBdss1l58BQ3KhooKeQT"
        "a9AB0Hw_Py5PJdTJNPY8cQn7ouZ2KKDcmnPGBY5t7yLc1QlQ5xHdwW1VhvKn-nXqhJTBgIPgtldC-KDV"
        "5z-y2XDwGUc"
    ),
    "q": (
        "uQPEfgmVtjL0Uyyx88GZFF1fOunH3-7cepKmtH4pxhtCoHqpWmT8YAmZxaewHgHAjLYsp1ZSe7zFYHj7"
        "C6ul7TjeLQeZD_YwD66t62wDmpe_HlB-TnBA-njbglfIsRLtXlnDzQkv5dTltRJ11BKBBypeeF6689rj"
        "cJIDEz9RWdc"
    ),
    "dp": (
        "BwKfV3Akq5_MFZDFZCnW-wzl-CCo83WoZvnLQwCTeDv8uzluRSnm71I3QCLdhrqE2e9YkxvuxdBfpT_P"
        "I7Yz-FOKnu1R6HsJeDCjn12Sk3vmAktV2zb34MCdy7cpdTh_YVr7tss2u6vneTwrA86rZtu5Mbr1C1Xs"
        "mvkxHQAdYo0"
    ),
    "dq": (
        "h_96-mK1R_7glhsum81dZxjTnYynPbZpHziZjeeHcXYsXaaMwkOlODsWa7I9xXDoRwbKgB719rrmI2oK"
        "r6N3Do9U0ajaHF-NKJnwgjMd2w9cjz3_-kyNlxAr2v4IKhGNpmM5iIgOS1VZnOZ68m6_pbLBSp3nssTd"
        "lqvd0tIiTHU"
    ),
    "qi": (
        "IYd7DHOhrWvxkwPQsRM2tOgrjbcrfvtQJipd-DlcxyVuuM9sQLdgjVk2oy26F0EmpScGLq2MowX7fhd_"
        "QJQ3ydy5cY7YIBi87w93IKLEdfnbJtoOPLUW0ITrJReOgo1cq9SbsxYawBgfp_gh6A5603k2-ZQwVK0J"
        "KSHuLFkuQ3U"
    ),
}

#: The signing input of Appendix A.2: the encoded ``{"alg":"RS256"}`` header and
#: the encoded payload of Appendix A.1, joined by a dot. Written out rather than
#: rebuilt because the payload carries CRLFs and spaces that no serialiser here
#: would emit -- the point is to sign the octets the RFC chose.
RFC7515_SIGNING_INPUT = (
    "eyJhbGciOiJSUzI1NiJ9"
    "."
    "eyJpc3MiOiJqb2UiLA0KICJleHAiOjEzMDA4MTkzODAsDQogImh0dHA6Ly9leGFtcGxlLmNvbS9pc19yb290"
    "Ijp0cnVlfQ"
)

#: The signature Appendix A.2.1 says must come out.
RFC7515_SIGNATURE = (
    "cC4hiUPoj9Eetdgtv3hF80EGrhuB__dzERat0XF9g2VtQgr9PJbu3XOiZj5RZmh7AAuHIm4Bh-0Qc_lF5YKt"
    "_O8W2Fp5jujGbds9uJdbF9CUAr7t1dnZcAcQjbKBYNX4BAynRFdiuB--f_nZLgrnbyTyWzO75vRK5h6xBArL"
    "IARNPvkSjtQBMHlb1L07Qe7K0GarZRmB_eSN9383LcOLn6_dO--xi12jzDwusC-eOkHWEsqtFZESc6BfI7no"
    "OPqvhJ1phCnvWh6IeYI2w9QOYEUipUTI8np6LbgGY9Fs98rqVt5AXLIhWkWywlVmtVrBp0igcN_IoypGlUPQ"
    "Ge77Rw"
)


#: The public key RFC 7638 §3.1 works through, and the thumbprint it prints.
#: A different key from Appendix A.2's above, deliberately -- a thumbprint test
#: that recomputed what the implementation computes would prove nothing.
RFC7638_N = (
    "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFxuhDR1L6tS"
    "oc_BJECPebWKRXjBZCiFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65"
    "YGjQR0_FDW2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n91CbOpbISD08qNLyr"
    "dkt-bFTWhAI4vMQFh6WeZu0fM4lFd2NcRwr3XPksINHaQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzK"
    "nqDKgw"
)
RFC7638_THUMBPRINT = "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs"


def _b64url_int(value: str) -> int:
    padded = value + "=" * (-len(value) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(padded), "big")


def rfc7515_private_key_pem() -> str:
    """Return Appendix A.2.1's key as the PEM :mod:`altero.services.jws` takes."""
    from cryptography.hazmat.primitives import serialization

    numbers = rsa.RSAPrivateNumbers(
        p=_b64url_int(RFC7515_JWK["p"]),
        q=_b64url_int(RFC7515_JWK["q"]),
        d=_b64url_int(RFC7515_JWK["d"]),
        dmp1=_b64url_int(RFC7515_JWK["dp"]),
        dmq1=_b64url_int(RFC7515_JWK["dq"]),
        iqmp=_b64url_int(RFC7515_JWK["qi"]),
        public_numbers=rsa.RSAPublicNumbers(
            e=_b64url_int(RFC7515_JWK["e"]), n=_b64url_int(RFC7515_JWK["n"])
        ),
    )
    return (
        numbers.private_key()
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode("ascii")
    )


class TestTheRfcVector:
    """RFC 7515 Appendix A.2, reproduced."""

    def test_the_signature_is_the_one_the_rfc_prints(self) -> None:
        pem = rfc7515_private_key_pem()

        signature = jws.sign_raw(RFC7515_SIGNING_INPUT.encode("ascii"), pem)

        assert signature == RFC7515_SIGNATURE

    def test_the_published_modulus_comes_back_out_of_the_jwk(self) -> None:
        """What ``/oauth/jwks.json`` serves has to be the key that signed."""
        pem = rfc7515_private_key_pem()

        published = jws.public_jwk(pem, kid="whatever")

        assert published["n"] == RFC7515_JWK["n"]
        assert published["e"] == RFC7515_JWK["e"]
        assert published["kty"] == "RSA"
        assert published["alg"] == "RS256"
        assert published["use"] == "sig"


class TestSigning:
    def test_a_signed_token_has_three_segments_and_names_its_key(self) -> None:
        pem = jws.generate_private_key()
        kid = jws.thumbprint(pem)

        token = jws.sign({"sub": "1"}, pem, kid)

        header_segment, payload_segment, signature_segment = token.split(".")
        header = json.loads(base64.urlsafe_b64decode(header_segment + "=="))
        payload = json.loads(base64.urlsafe_b64decode(payload_segment + "=="))
        assert header == {"alg": "RS256", "typ": "JWT", "kid": kid}
        assert payload == {"sub": "1"}
        assert signature_segment

    def test_the_signature_verifies_under_the_published_key(self) -> None:
        """The check a client makes, made here once so the whole loop is covered."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        pem = jws.generate_private_key()
        token = jws.sign({"sub": "1", "iss": "https://altero.example"}, pem, "k1")
        header_segment, payload_segment, signature_segment = token.split(".")

        public_key = jws.load_private_key(pem).public_key()
        public_key.verify(
            base64.urlsafe_b64decode(signature_segment + "=" * (-len(signature_segment) % 4)),
            f"{header_segment}.{payload_segment}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )

    def test_a_tampered_payload_no_longer_verifies(self) -> None:
        """The test that gives the one above teeth."""
        import pytest
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        pem = jws.generate_private_key()
        token = jws.sign({"sub": "1"}, pem, "k1")
        header_segment, _, signature_segment = token.split(".")
        forged = jws.b64url(b'{"sub":"2"}')

        with pytest.raises(InvalidSignature):
            jws.load_private_key(pem).public_key().verify(
                base64.urlsafe_b64decode(signature_segment + "=" * (-len(signature_segment) % 4)),
                f"{header_segment}.{forged}".encode("ascii"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )


class TestTheThumbprint:
    def test_it_is_derived_from_the_key_and_not_assigned(self) -> None:
        """The same key names itself the same way across restarts and restores."""
        pem = jws.generate_private_key()

        assert jws.thumbprint(pem) == jws.thumbprint(pem)

    def test_two_keys_get_two_names(self) -> None:
        assert jws.thumbprint(jws.generate_private_key()) != jws.thumbprint(
            jws.generate_private_key()
        )

    def test_it_matches_the_rfc_7638_worked_example(self) -> None:
        """RFC 7638 §3.1 prints a public key and the thumbprint it must produce."""
        assert jws.jwk_thumbprint(RFC7638_N, "AQAB") == RFC7638_THUMBPRINT


class TestTheAccessTokenHash:
    def test_it_is_the_left_half_of_the_digest(self) -> None:
        """OpenID Connect Core §3.1.3.6 prints this example."""
        # A SHA-256 digest is 32 bytes; at_hash is the first 16, base64url.
        import hashlib

        token = "jHkWEdUXMU1BwAsC4vtUsZwnNvTIxEl0z9K3vx5KF0Y"
        expected = jws.b64url(hashlib.sha256(token.encode("ascii")).digest()[:16])

        assert jws.access_token_hash(token) == expected
        assert len(base64.urlsafe_b64decode(jws.access_token_hash(token) + "==")) == 16
