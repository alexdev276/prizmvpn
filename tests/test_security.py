from datetime import timedelta

from app.core.security import create_access_token, decode_access_token, generate_token, hash_token, verify_token_hash


def test_token_hash_verification() -> None:
    token = generate_token()
    token_hash = hash_token(token)

    assert verify_token_hash(token, token_hash)
    assert not verify_token_hash("wrong-token", token_hash)


def test_jwt_roundtrip() -> None:
    token = create_access_token("42", expires_delta=timedelta(minutes=5))

    assert decode_access_token(token) == "42"

