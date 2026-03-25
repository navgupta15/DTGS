package com.example;

import org.springframework.web.bind.annotation.*;
import java.util.List;

/**
 * Sample controller demonstrating various Java method patterns
 * for use in toolmaker unit tests.
 */
@RestController
@RequestMapping("/api")
public class SampleController {

    /**
     * Returns a greeting message for the given user name.
     * @param name The name of the user to greet.
     * @return A greeting string.
     */
    @GetMapping("/greet")
    public String greet(String name) {
        return "Hello, " + name + "!";
    }

    /**
     * Adds two integers and returns their sum.
     * @param a First integer operand.
     * @param b Second integer operand.
     * @return The sum of a and b.
     */
    public int add(int a, int b) {
        return a + b;
    }

    /**
     * Checks whether a value is positive.
     */
    public boolean isPositive(double value) {
        return value > 0;
    }

    /**
     * Returns a list of items matching the query.
     */
    @GetMapping("/search")
    public List<String> search(String query, int limit) {
        return List.of();
    }

    /**
     * Creates a new resource from JSON payload.
     */
    @PostMapping("/resource")
    public String createResource(String payload) {
        return "created";
    }

    // Private method — should still be captured with private modifier
    private void internalHelper(String data) {
        // no-op
    }

    /**
     * Computes factorial recursively.
     * @param n Non-negative integer.
     * @return n!
     */
    public static long factorial(int n) {
        if (n <= 1) return 1;
        return n * factorial(n - 1);
    }
}
