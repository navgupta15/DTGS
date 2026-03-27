from toolmaker.registry.openapi_generator import _parse_rest_annotation

test_str = '@RequestMapping(value = "/{id}", method = RequestMethod.GET)'
verb, path = _parse_rest_annotation("MyCtrl_getPet", test_str)
print(f"VERB: {verb}, PATH: {path}")
