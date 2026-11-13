import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["REDIS_URL"] = "redis://localhost:1/0"  # недоступний — rate limit піде в пам'ять
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Courier, Role, User
from app.security import hash_password


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make_user(email, role, password="password123"):
    db = SessionLocal()
    user = User(email=email, full_name=email.split("@")[0], password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user


def make_courier(email, lat, lon, online=True, vehicle="bike"):
    user = make_user(email, Role.courier)
    db = SessionLocal()
    courier = Courier(user_id=user.id, lat=lat, lon=lon, is_online=online, vehicle=vehicle)
    db.add(courier)
    db.commit()
    db.refresh(courier)
    db.close()
    return courier


def token_for(client, email, password="password123"):
    resp = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def client_headers(client):
    make_user("client@test.ua", Role.client)
    return token_for(client, "client@test.ua")


@pytest.fixture
def dispatcher_headers(client):
    make_user("dispatcher@test.ua", Role.dispatcher)
    return token_for(client, "dispatcher@test.ua")
