import uuid


def test_items_require_auth(client):
    assert client.get("/v1/items").status_code == 401
    assert client.post("/v1/items", json={"name": "x"}).status_code == 401


def test_create_list_get(client, auth_headers):
    created = client.post("/v1/items", json={"name": "Widget"}, headers=auth_headers)
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Widget"
    assert body["status"] == "active"

    listed = client.get("/v1/items", headers=auth_headers)
    assert [i["id"] for i in listed.json()] == [body["id"]]

    fetched = client.get(f"/v1/items/{body['id']}", headers=auth_headers)
    assert fetched.json() == body


def test_get_missing_item(client, auth_headers):
    resp = client.get(f"/v1/items/{uuid.uuid4()}", headers=auth_headers)
    assert resp.status_code == 404


def test_create_validates_name(client, auth_headers):
    assert client.post("/v1/items", json={"name": ""}, headers=auth_headers).status_code == 422
