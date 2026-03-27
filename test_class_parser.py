from toolmaker.registry.openapi_generator import _parse_rest_annotation

method_str = '@RequestMapping(value = "/{id}", method = RequestMethod.GET)'
class_str = '@RequestMapping("/pet")'
verb, path = _parse_rest_annotation("MyCtrl_getPet", method_str, class_str)
print(f"VERB: {verb}, PATH: {path}")
