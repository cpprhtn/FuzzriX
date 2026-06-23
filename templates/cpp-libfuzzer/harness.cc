// FuzzriX libFuzzer harness template (C/C++).
//
// The agent fills in: the include for the target's header, and the call that maps the fuzzer's raw bytes
// onto the target function's arguments. Keep it minimal, deterministic, crash-only — no prints, no I/O,
// no state that survives between calls. See references/harness-generation.md.
//
// Build (inside the container):
//   clang++ -g -O1 -fsanitize=fuzzer,address,undefined harness.cc <target sources> -I <inc> -o /fuzzer

#include <cstdint>
#include <cstddef>
#include <cstring>

// If the target is C, wrap its header so C++ links against it correctly:
//   extern "C" {
//   #include "target.h"
//   }
// For C++ targets, just include the header:
//   #include "target.hpp"
#include "TARGET_HEADER.h"  // <-- agent: replace

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // Reject inputs too short to be meaningful for this target.
    if (size < 1) return 0;

    // --- agent: map bytes -> target arguments and call it -------------------
    // Case A — target already takes (buffer, length):
    //     parse_thing(data, size);
    //
    // Case B — target needs structured args; carve them deterministically:
    //     if (size < 5) return 0;
    //     uint32_t opts; std::memcpy(&opts, data, 4);
    //     decode_frame(opts, data + 4, size - 4);
    //
    // Case C — target wants a NUL-terminated C string: copy into a bounded,
    // null-terminated buffer (don't assume `data` is terminated):
    //     char buf[256];
    //     size_t n = size < sizeof(buf) - 1 ? size : sizeof(buf) - 1;
    //     std::memcpy(buf, data, n); buf[n] = '\0';
    //     handle_string(buf);
    // ------------------------------------------------------------------------

    return 0;  // non-zero is reserved by libFuzzer; always return 0
}
