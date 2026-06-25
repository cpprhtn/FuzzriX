# JVM Jazzer template

Starting point for the dual artifact (harness + Dockerfile) on a **Java / JVM**
target (Kotlin/Scala too). [Jazzer](https://github.com/CodeIntelligenceTesting/jazzer)
is libFuzzer for the JVM — same engine, same `/fuzzer` entry point, same
`run_fuzz.sh`, same libFuzzer flags. See
[`references/harness-generation.md` § Java/JVM](../../references/harness-generation.md#jvm-jazzer).

## Files

- [`Fuzzer.java`](Fuzzer.java) — `fuzzerTestOneInput(FuzzedDataProvider)` skeleton.
  Replace the target call and narrow the `catch` to the parser's declared failure
  mode only.
- [`Dockerfile`](Dockerfile) — OSS-Fuzz JVM base (bundles Jazzer + JDK), with the
  `-encoding UTF-8` and arm64 fixes baked in. Installs a `/fuzzer` wrapper.

## Quick start (agent)

```bash
# 1. build context
mkdir -p fuzz && cp templates/jvm-jazzer/{Fuzzer.java,Dockerfile} fuzz/
#    point the Dockerfile at the target jar (COPY a built jar or curl a published one)

# 2. build + run (arm64 host: prefix with the platform)
DOCKER_DEFAULT_PLATFORM=linux/amd64 bash scripts/run_fuzz.sh fuzz/ out/ 120
```

## What counts as a finding

A managed runtime has no memory corruption — the engine surfaces:

- an **uncaught exception / `Error`** (so catch only the *expected* exception type;
  let a `StackOverflowError`, `OutOfMemoryError`, or an unexpected exception crash);
- a **`FuzzerSecurityIssue*`** from a Jazzer **bug detector** — SSRF, OS command
  injection, path traversal, **unsafe deserialization / RCE**, LDAP/SQL/expression
  injection — which turns a silent reachable sink into a crash.

`crash-triage` classifies a `FuzzerSecurityIssue` as a real security finding (with
Jazzer's severity) and a plain uncaught exception as a managed-runtime DoS.
