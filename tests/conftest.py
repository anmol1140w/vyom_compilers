from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("VYOM_VISION_MODEL", raising=False)
    with TestClient(create_app(tmp_path / "data")) as client:
        yield client


@pytest.fixture
def upload(client):
    def send(filename="sample-invoices.csv", contents=None, **form):
        if contents is None:
            contents = (ROOT / "samples" / filename).read_bytes()
        return client.post("/api/documents", files={"file": (filename, contents)}, data=form)

    return send
