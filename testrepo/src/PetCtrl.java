
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
