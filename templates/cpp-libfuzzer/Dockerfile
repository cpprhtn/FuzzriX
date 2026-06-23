# FuzzriX libFuzzer Dockerfile template (C/C++).
#
# Trusted base: aflplusplus/aflplusplus ships clang, AFL++, and the sanitizer runtimes — so both libFuzzer
# and AFL++ work from the same image. Pin the tag for reproducibility. The agent edits the build RUN line
# to match the project's sources / include dirs / deps, self-healing on errors (see
# references/self-healing.md, references/dockerfile-generation.md).

# NOTE: aflplusplus version tags carry a leading 'v' (e.g. v4.21c, v5.00c) — a
# bare '4.21c' does NOT exist and the build will fail at the FROM line.
FROM aflplusplus/aflplusplus:v4.21c

ENV CC=clang CXX=clang++
WORKDIR /src

# Install any extra build dependencies the target needs (agent fills in; keep minimal):
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     libfoo-dev zlib1g-dev && rm -rf /var/lib/apt/lists/*

# Copy the build context (project source + harness.cc) in. Source last keeps the layer cache warm
# across self-heal edits.
COPY . /src

RUN mkdir -p /out

# --- Build the fuzzer (agent: edit sources / -I include dirs / -l libs) -----
# IMPORTANT: emit the binary OUTSIDE /out. run_fuzz.sh bind-mounts the host
# out-dir over /out at run time, which would mask a binary built into /out.
#
# C++ target — compile sources + harness directly with clang++:
RUN clang++ -g -O1 -fsanitize=fuzzer,address,undefined \
        harness.cc \
        src/TARGET.cc \
        -I src \
        -o /fuzzer

# C target — compile the .c as C (clang, NOT clang++: clang++ builds it in C++
# mode and name-mangles the symbols, breaking the harness's extern "C" linkage
# with "undefined reference"). Instrument with fuzzer-no-link, then link:
#   RUN clang -g -O1 -fsanitize=fuzzer-no-link,address,undefined \
#           -I include -c src/TARGET.c -o /TARGET.o
#   RUN clang++ -g -O1 -fsanitize=fuzzer,address,undefined \
#           harness.cc /TARGET.o -I include -o /fuzzer

# CMake case — build the lib with sanitizers, then link the harness against it:
#   ENV CFLAGS="-g -O1 -fsanitize=address,undefined -fsanitize=fuzzer-no-link" \
#       CXXFLAGS="-g -O1 -fsanitize=address,undefined -fsanitize=fuzzer-no-link"
#   RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug && cmake --build build -j
#   RUN clang++ -g -O1 -fsanitize=fuzzer,address,undefined \
#           harness.cc -I include -Lbuild -lYOURLIB -o /fuzzer
# ---------------------------------------------------------------------------

# Run is driven from the host with resource caps via scripts/run_fuzz.sh; the binary lives at /fuzzer.
# Sane sanitizer defaults if run directly:
ENV ASAN_OPTIONS=abort_on_error=1:detect_leaks=1:symbolize=1 \
    UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1
