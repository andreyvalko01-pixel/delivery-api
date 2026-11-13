import hashlib
import hmac
import json

from app.config import settings
from app.geo import haversine_km
from tests.conftest import make_courier, token_for

ORDER = {
    "pickup_address": "Київ, вул. Хрещатик, 22",
    "pickup": {"lat": 50.4474, "lon": 30.5225},
    "dropoff_address": "Київ, вул. Антоновича, 50",
    "dropoff": {"lat": 50.4320, "lon": 30.5110},
    "weight_kg": 2,
}


def create_order(client, headers, **extra):
    resp = client.post("/api/v1/orders", json={**ORDER, **extra}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_haversine():
    # Київ -> Львів ~ 470 км по прямій
    assert 460 < haversine_km(50.45, 30.52, 49.84, 24.03) < 480


def test_register_and_login(client):
    resp = client.post("/api/v1/auth/register", json={
        "email": "New@Mail.com", "password": "secret123", "full_name": "Тест", "phone": "+380671234567",
    })
    assert resp.status_code == 201
    assert resp.json()["email"] == "new@mail.com"

    again = client.post("/api/v1/auth/register", json={"email": "new@mail.com", "password": "secret123", "full_name": "X1"})
    assert again.status_code == 409

    headers = token_for(client, "new@mail.com", "secret123")
    assert client.get("/api/v1/auth/me", headers=headers).json()["role"] == "client"


def test_requires_auth(client):
    assert client.get("/api/v1/orders").status_code == 401


def test_order_price_and_history(client, client_headers):
    order = create_order(client, client_headers)
    assert order["status"] == "created"
    assert order["price"] > 60

    detail = client.get(f"/api/v1/orders/{order['id']}", headers=client_headers).json()
    assert [h["status"] for h in detail["history"]] == ["created"]


def test_client_cannot_see_foreign_order(client, client_headers):
    order = create_order(client, client_headers)
    client.post("/api/v1/auth/register", json={"email": "other@test.ua", "password": "password123", "full_name": "Other"})
    other = token_for(client, "other@test.ua")
    assert client.get(f"/api/v1/orders/{order['id']}", headers=other).status_code == 404


def test_nearby_couriers_sorted_and_busy_excluded(client, client_headers, dispatcher_headers):
    near = make_courier("near@test.ua", 50.4480, 30.5230)
    far = make_courier("far@test.ua", 50.4700, 30.5500)
    make_courier("offline@test.ua", 50.4475, 30.5226, online=False)

    resp = client.get("/api/v1/couriers/nearby", params={"lat": 50.4474, "lon": 30.5225, "radius_km": 10},
                      headers=dispatcher_headers)
    ids = [c["id"] for c in resp.json()]
    assert ids == [near.id, far.id]

    # після призначення найближчий стає зайнятим
    order = create_order(client, client_headers)
    assigned = client.post(f"/api/v1/orders/{order['id']}/assign", json={}, headers=dispatcher_headers).json()
    assert assigned["courier_id"] == near.id
    assert assigned["eta_minutes"] > 10

    resp = client.get("/api/v1/couriers/nearby", params={"lat": 50.4474, "lon": 30.5225, "radius_km": 10},
                      headers=dispatcher_headers)
    assert [c["id"] for c in resp.json()] == [far.id]


def test_status_flow(client, client_headers, dispatcher_headers):
    make_courier("c1@test.ua", 50.448, 30.523)
    order = create_order(client, client_headers)
    client.post(f"/api/v1/orders/{order['id']}/assign", json={}, headers=dispatcher_headers)

    courier_headers = token_for(client, "c1@test.ua")
    for status in ("picked_up", "in_transit", "delivered"):
        resp = client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": status}, headers=courier_headers)
        assert resp.status_code == 200, resp.text

    # з "доставлено" вже нікуди
    resp = client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "cancelled"}, headers=dispatcher_headers)
    assert resp.status_code == 409


def test_client_can_only_cancel(client, client_headers):
    order = create_order(client, client_headers)
    resp = client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "delivered"}, headers=client_headers)
    assert resp.status_code == 403
    resp = client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "cancelled"}, headers=client_headers)
    assert resp.json()["status"] == "cancelled"


def _signed(payload: dict):
    body = json.dumps(payload).encode()
    sig = hmac.new(settings.np_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Signature": sig, "Content-Type": "application/json"}


def test_nova_poshta_webhook(client, client_headers, dispatcher_headers):
    make_courier("c2@test.ua", 50.448, 30.523)
    order = create_order(client, client_headers, np_ttn="20450000000001")
    client.post(f"/api/v1/orders/{order['id']}/assign", json={}, headers=dispatcher_headers)
    client.patch(f"/api/v1/orders/{order['id']}/status", json={"status": "picked_up"}, headers=dispatcher_headers)

    body, headers = _signed({"ttn": "20450000000001", "status_code": 7, "status": "Прибуло на відділення"})
    assert client.post("/api/v1/webhooks/nova-poshta", content=body, headers=headers).json()["changed"] is True

    body, headers = _signed({"ttn": "20450000000001", "status_code": 9, "status": "Отримано"})
    client.post("/api/v1/webhooks/nova-poshta", content=body, headers=headers)
    assert client.get(f"/api/v1/orders/{order['id']}", headers=client_headers).json()["status"] == "delivered"


def test_webhook_rejects_bad_signature(client):
    resp = client.post("/api/v1/webhooks/nova-poshta", content=b'{"ttn":"1","status_code":9,"status":"x"}',
                       headers={"X-Signature": "wrong"})
    assert resp.status_code == 401


def test_rate_limit():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.rate_limit import MemoryBackend, RateLimitMiddleware

    mini = FastAPI()
    mini.add_middleware(RateLimitMiddleware, limit=3, backend=MemoryBackend())

    @mini.get("/ping")
    def ping():
        return "pong"

    with TestClient(mini) as c:
        codes = [c.get("/ping").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
