from toolmaker.analyzer.java_analyzer import _parser

src = b'''
import org.springframework.web.bind.annotation.*;

@RestController
public class MyCtrl {
    @RequestMapping(value = "/{id}", method = RequestMethod.GET)
    public String getPet(@PathVariable String id) {
        return "pet";
    }
}
'''
from toolmaker.analyzer.java_analyzer import analyze_file
# Let's write the src to testrepo/src/MyCtrl.java and parse it using the real java_analyzer function to see what it extracts
with open("testrepo/src/MyCtrl.java", "wb") as f:
    f.write(src)

from pathlib import Path
methods = analyze_file(Path("testrepo/src/MyCtrl.java"))
print("METHODS:", len(methods))
for m in methods:
    print(m.method_name, m.rest_annotations)
