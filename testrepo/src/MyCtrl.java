
import org.springframework.web.bind.annotation.*;

@RestController
public class MyCtrl {
    @RequestMapping(value = "/{id}", method = RequestMethod.GET)
    public String getPet(@PathVariable String id) {
        return "pet";
    }
}
