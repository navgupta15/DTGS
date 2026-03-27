from pathlib import Path
from toolmaker.analyzer.java_analyzer import analyze_file
from toolmaker.analyzer.schema_generator import methods_to_tool_schemas
from toolmaker.models import AnalyzedClass
import json

src = b'''
public class PetDto {
    private String name;
    private int age;
    private List<String> tags;
}

@RestController
@RequestMapping("/api/pets")
public class PetController {
    @PostMapping
    public void createPet(@RequestBody PetDto pet) {
    }
}
'''

with open("testrepo/src/PetCtrl.java", "wb") as f:
    f.write(src)

methods, classes = analyze_file(Path("testrepo/src/PetCtrl.java"))
print(f"Parsed {len(methods)} methods, {len(classes)} classes")

registry: dict[str, AnalyzedClass] = {c.class_name: c for c in classes}
schemas = methods_to_tool_schemas(methods, registry)

for s in schemas:
    print(json.dumps(s.model_dump(), indent=2))
