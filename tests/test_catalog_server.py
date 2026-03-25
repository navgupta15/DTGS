from fastapi.testclient import TestClient
from toolmaker.server.catalog import app
from toolmaker.registry.sqlite_registry import ToolRegistry

client = TestClient(app)

def test_catalog_server_returns_404_for_unknown_namespace(tmp_path):
    # Setup state manually for TestClient
    app.state.registry_path = str(tmp_path / "test.db")
    app.state.registry = ToolRegistry(app.state.registry_path)
    
    response = client.get("/api/v1/unknown/openapi.json")
    assert response.status_code == 404
    assert "No tools found" in response.json()["detail"]

def test_catalog_server_returns_openapi_spec(tmp_path):
    # Setup dummy database with one tool
    db_path = str(tmp_path / "test.db")
    registry = ToolRegistry(db_path)
    
    schema = {
        "function": {
            "name": "Test_endpoint",
            "description": "REST endpoint (@GetMapping(\"/test\"))",
            "parameters": {"type": "object", "properties": {}}
        }
    }
    registry.upsert_many(
        schemas=[schema],
        namespace="my_service",
        base_url="http://test.com"
    )
    
    app.state.registry_path = db_path
    app.state.registry = registry
    
    response = client.get("/api/v1/my_service/openapi.json")
    assert response.status_code == 200
    
    data = response.json()
    assert data["openapi"] == "3.1.0"
    assert "my_service" in data["info"]["title"]
    assert data["servers"][0]["url"] == "http://test.com"
    assert "/test" in data["paths"]
