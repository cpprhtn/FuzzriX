# Authorization & safety gate

Fuzzing is *running code while feeding it hostile input as fast as possible*. That makes it both legally and
operationally dangerous if pointed at the wrong thing. Pass this gate **every time**, before any build/run.

## Who/what you may fuzz

| Target | Allowed? | Notes |
|---|---|---|
| Source repo the user owns / controls | ✅ Implicit | the normal case |
| OSS the user contributes to / has permission to test | ✅ | this is exactly what Google's OSS-Fuzz does |
| Third-party software the user does **not** control | ⚠️ Only with written permission / bounty scope | get it in writing first |
| A **live production service** or **remote host/IP** | ⛔ Stop | FuzzriX fuzzes *code in a sandbox*, not live endpoints; pointing a fuzzer at a remote host is a DoS |

If you can't establish authorization for a third party → **stop**, and offer to fuzz code the user does own,
or set up the harness without running it against the unauthorized target.

## Refuse to weaponize

Decline if the evident purpose is harming a third party: building a crasher/DoS payload against software the
user doesn't control, or producing exploit primitives aimed at a named external target. Finding bugs in your
*own* code (even exploitable ones) so you can fix them is the whole point and is fine.

## Mandatory safety invariants (enforce on every run)

1. **Sandbox everything.** Compile and execute target code **only inside Docker**. Never run an
   LLM-generated harness or an untrusted target's build on the host — a malicious or buggy `CMakeLists.txt`
   can run arbitrary commands at configure time.
2. **Cap resources before launch.** Always set, on the `docker run`:
   - time: `-max_total_time=<seconds>` (libFuzzer) / `timeout` wrapper — default short (60–300s).
   - memory: `--memory=<e.g. 2g>` and libFuzzer `-rss_limit_mb`.
   - cpu: `--cpus=<n>`; disk: bound the corpus/crash dir; consider `--pids-limit`.
   - network: `--network=none` unless the target genuinely needs it (most don't).
3. **No auto-exfiltration.** Crash testcases may contain sensitive data from the corpus. Keep artifacts local
   under the user's output dir; don't upload anywhere without explicit ask.
4. **Confirm destructive-looking targets.** If a target function deletes files, calls `system()`, or touches
   the network, say so and confirm before fuzzing it (even sandboxed, the agent should flag intent).

## Quick gate script

State, in one line, before building: *"Fuzzing <repo> (owned by user) in Docker, capped at <N>s /
<M>g RAM / <C> cpus, network off, output → <dir>."* If you can't fill that in, you haven't passed the gate.
