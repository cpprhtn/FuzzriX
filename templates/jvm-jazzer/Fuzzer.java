// FuzzriX Jazzer harness template (Java / JVM — Kotlin/Scala work the same way).
// Jazzer is libFuzzer for the JVM: same engine, a JVM agent supplies coverage.
//
// Fill in:
//   1. the call into the target library (replace the snakeyaml line);
//   2. the catch clause — list ONLY the target's *declared* failure mode
//      (usually a RuntimeException subtype). Everything else you let through is
//      the finding: a StackOverflowError / OutOfMemoryError (DoS), an unexpected
//      exception from library code, or a Jazzer bug-detector FuzzerSecurityIssue
//      (RCE / SSRF / injection / unsafe deserialization).
import com.code_intelligence.jazzer.api.FuzzedDataProvider;

public class Fuzzer {

    // Optional one-time setup (loaded once per process, never per input):
    // public static void fuzzerInitialize() { /* ... */ }

    public static void fuzzerTestOneInput(FuzzedDataProvider data) {
        try {
            // EXAMPLE — replace with the target API under test:
            new org.yaml.snakeyaml.Yaml().load(data.consumeRemainingAsString());
        } catch (IllegalArgumentException expected) {
            // input the parser rejects by design — not a bug
        }
    }

    // Alternative signature when you want the raw bytes:
    //   public static void fuzzerTestOneInput(byte[] input) { ... }
}
