def test_packs_endpoint_lists_shipped_packs(client):
    r = client.get("/packs")
    assert r.status_code == 200
    ids = {p["id"] for p in r.json()}
    assert {"dentist", "salon"} <= ids
