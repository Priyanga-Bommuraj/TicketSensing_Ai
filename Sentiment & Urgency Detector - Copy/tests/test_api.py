from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_empty_ticket_validation():
    response = client.post("/analyze", json={"text": ""})
    assert response.status_code == 400