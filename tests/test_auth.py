"""Admin login, sessions and the lock after too many wrong passwords."""

from dataclasses import replace

from conftest import PASSWORD

from image_generator.auth import LoginLimiter, SessionStore, password_matches


class FakeClock:
    """A clock the test can move forward."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_login_logout_flow(client):
    assert client.get("/api/session").json() == {"admin": False}
    assert client.post("/api/login", json={"password": "nope"}).json() == {"error": "Verkeerd wachtwoord."}

    response = client.post("/api/login", json={"password": PASSWORD})
    assert response.json() == {"admin": True}
    cookie = response.headers["set-cookie"]
    assert "admin_session=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    assert "Secure" not in cookie
    assert client.get("/api/session").json() == {"admin": True}

    assert client.post("/api/logout").json() == {"admin": False}
    assert client.get("/api/session").json() == {"admin": False}
    assert client.get("/api/words").status_code == 401
    assert client.post("/api/logout").status_code == 200  # logging out twice is fine


def test_cookie_is_secure_behind_https_tunnel(client):
    response = client.post("/api/login", json={"password": PASSWORD}, headers={"x-forwarded-proto": "https"})
    assert "Secure" in response.headers["set-cookie"]


def test_password_must_be_a_string(client):
    assert client.post("/api/login", json={"password": 123}).status_code == 401


def test_login_without_admin_password_is_locked(make_client, settings):
    client = make_client(replace(settings, admin_password=""))
    response = client.post("/api/login", json={"password": ""})
    assert response.status_code == 503
    assert "ADMIN_PASSWORD" in response.json()["error"]


def test_lockout_after_five_wrong_passwords_per_visitor(client):
    visitor = {"cf-connecting-ip": "1.2.3.4"}
    for _ in range(5):
        assert client.post("/api/login", json={"password": "nope"}, headers=visitor).status_code == 401
    locked = client.post("/api/login", json={"password": PASSWORD}, headers=visitor)
    assert locked.status_code == 429
    assert locked.json() == {"error": "Te vaak een verkeerd wachtwoord. Probeer het over 15 minuut/minuten opnieuw."}
    # Another visitor is not affected.
    other = client.post("/api/login", json={"password": PASSWORD}, headers={"cf-connecting-ip": "5.6.7.8"})
    assert other.status_code == 200


def test_password_matches():
    assert password_matches("secret", "secret")
    assert not password_matches("wrong", "secret")
    assert not password_matches("", "")


def test_sessions_expire():
    clock = FakeClock()
    sessions = SessionStore(lifetime=60, clock=clock)
    token = sessions.create()
    assert sessions.is_valid(token)
    assert not sessions.is_valid(None)
    assert not sessions.is_valid("unknown")
    clock.now += 61
    assert not sessions.is_valid(token)
    assert not sessions.is_valid(token)  # also after it was cleaned up
    sessions.end(None)
    sessions.end(token)


def test_limiter_lock_wears_off_and_resets_on_success():
    clock = FakeClock()
    limiter = LoginLimiter(max_attempts=2, lock_seconds=600, clock=clock)
    assert limiter.minutes_locked("ip") == 0
    limiter.failed("ip")
    assert limiter.minutes_locked("ip") == 0
    limiter.failed("ip")
    assert limiter.minutes_locked("ip") == 10
    clock.now += 601
    assert limiter.minutes_locked("ip") == 0
    limiter.failed("ip")
    limiter.succeeded("ip")
    limiter.failed("ip")
    assert limiter.minutes_locked("ip") == 0
