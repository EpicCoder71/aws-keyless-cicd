import json
import pytest
from src.app import handler

@pytest.mark.parametrize("path", ["/", "/health"])
def test_health(path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    result = handler({"rawPath": path}, None)
    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"status": "ok", "service": "keyless-cicd", "environment": "dev"}
    assert result["headers"]["content-type"] == "application/json"

@pytest.mark.parametrize("event, status", [({"rawPath": "/missing"}, 404), ({"requestContext": {"http": {"method": "POST"}}}, 405), (None, 200)])
def test_routes(event, status):
    assert handler(event, None)["statusCode"] == status
