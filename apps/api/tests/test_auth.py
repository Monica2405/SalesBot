import time

import jwt

TEST_USER_ID = "11111111-1111-1111-1111-111111111111"


def _token(secret: str, **overrides) -> str:
    claims = {
        "sub": TEST_USER_ID,
        "aud": "authenticated",
        "role": "authenticated",
        "email": "owner@demo.local",
        "exp": int(time.time()) + 60,
    }
    claims.update(overrides)
    return jwt.encode(claims, secret, algorithm="HS256")


def test_me_requires_token(client):
    assert client.get("/me").status_code == 401


def test_me_with_valid_supabase_token(client, settings):
    token = _token(settings.supabase_jwt_secret.get_secret_value())
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["id"] == TEST_USER_ID


def test_me_rejects_wrong_secret(client):
    token = _token("some-other-secret-that-is-long-enough!!")
    assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_me_rejects_expired_token(client, settings):
    token = _token(settings.supabase_jwt_secret.get_secret_value(), exp=int(time.time()) - 10)
    assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_me_rejects_wrong_audience(client, settings):
    token = _token(settings.supabase_jwt_secret.get_secret_value(), aud="anon")
    assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
