# FuzzriX Atheris Dockerfile template (Python).
#
# atheris install is environment-sensitive — this base bakes in the three fixes
# that each otherwise cause a hard failure (all hit during FuzzriX dogfooding):
#   1. Python 3.11+      — recent atheris uses dis.Positions; 3.10 dies at import
#                          ("module 'dis' has no attribute 'Positions'").
#   2. libclang-rt-*-dev — ships the libFuzzer .a; `clang` alone (with
#                          --no-install-recommends) omits it → "Failed to find
#                          libFuzzer archive".
#   3. CLANG_BIN + CC/CXX — atheris needs CLANG_BIN to locate that archive; a
#                          minimal image with no gcc otherwise errors
#                          "Unsupported compiler".

FROM python:3.11
ENV DEBIAN_FRONTEND=noninteractive
ENV CC=clang CXX=clang++ CLANG_BIN=clang

# NOTE: match the rt package version to the image's clang (python:3.11 → debian
# trixie → clang-19 → libclang-rt-19-dev). If the base changes, update the
# version suffix, or the atheris wheel build fails to find libFuzzer.
RUN apt-get update && apt-get install -y --no-install-recommends \
        clang libclang-rt-19-dev && \
    pip3 install --no-cache-dir atheris && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . /src

# Install the target if it's a package (agent: uncomment / adjust):
# RUN pip3 install -e .
# RUN pip3 install -r requirements.txt

# Unify the run entry point with the C/C++ engines: run_fuzz.sh launches /fuzzer
# with libFuzzer-style flags, and an atheris harness IS a libFuzzer driver, so a
# tiny wrapper makes Python reuse the exact same run_fuzz.sh.
RUN printf '#!/bin/sh\nexec python3 /src/harness.py "$@"\n' > /fuzzer && \
    chmod +x /fuzzer
