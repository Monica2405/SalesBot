def test_health_ok_without_database(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "env": "local"}


def test_health_db_reports_not_configured(client):
    assert client.get("/health/db").json() == {"database": "not_configured"}
