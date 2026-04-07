from toolmaker.registry.openapi_generator import _parse_rest_annotation, generate_openapi_spec

def test_parse_rest_annotation():
    # Standard Spring Boot annotations
    assert _parse_rest_annotation("mock", '@GetMapping("/api/pets")') == ("get", "/api/pets")
    assert _parse_rest_annotation("mock", '@PostMapping(value = "/save")') == ("post", "/save")
    assert _parse_rest_annotation("mock", '@RequestMapping(path="/delete", method=RequestMethod.DELETE)') == ("delete", "/delete")
    
    # Default mapping without method
    assert _parse_rest_annotation("mock", '@RequestMapping("/fallback")') == ("get", "/fallback")
    
    # Missing annotation fallback
    assert _parse_rest_annotation("myFunc", '') == ("get", "/myFunc")

def test_generate_openapi_spec():
    schemas = [
        {
            "function": {
                "name": "UserController_getUser",
                "description": "REST endpoint (@GetMapping(\"/users/{id}\")): Gets user",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "User ID"}
                    },
                    "required": ["id"]
                },
                "__rest_annotations": ["@GetMapping(\"/users/{id}\")"]
            }
        },
        {
            "function": {
                "name": "UserController_createUser",
                "description": "REST endpoint (@PostMapping(\"/users\")): Creates user",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer"}
                    },
                    "required": ["name"]
                },
                "__rest_annotations": ["@PostMapping(\"/users\")"]
            }
        }
    ]
    
    spec = generate_openapi_spec("auth_service", schemas, "https://api.auth.com")
    
    assert spec["openapi"] == "3.1.0"
    assert "auth_service" in spec["info"]["title"]
    assert spec["servers"][0]["url"] == "https://api.auth.com"
    
    paths = spec["paths"]
    
    # Check GET /users/{id}
    assert "/users/{id}" in paths
    get_op = paths["/users/{id}"]["get"]
    assert get_op["operationId"] == "UserController_getUser"
    
    # Must correctly identify {id} as a path parameter
    params = get_op["parameters"]
    assert len(params) == 1
    assert params[0]["name"] == "id"
    assert params[0]["in"] == "path"
    
    # Check POST /users
    assert "/users" in paths
    post_op = paths["/users"]["post"]
    assert post_op["operationId"] == "UserController_createUser"
    
    # Must place properties into requestBody for POST
    assert "parameters" not in post_op  # No path params
    body = post_op["requestBody"]["content"]["application/json"]["schema"]
    assert "name" in body["properties"]
    assert "age" in body["properties"]
    assert "name" in body["required"]
