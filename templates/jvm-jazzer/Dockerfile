# FuzzriX Jazzer Dockerfile template (Java / JVM).
#
# The OSS-Fuzz JVM base image bundles a *working* Jazzer (driver + agent) and a
# JDK, so there's no platform-specific native-driver wrangling. Two gotchas baked
# in (both hit during FuzzriX dogfooding):
#   1. javac defaults to the image's US-ASCII locale → any non-ASCII byte in the
#      source (a comment, a string literal) fails with "unmappable character".
#      Always pass `-encoding UTF-8`.
#   2. On Apple-silicon / arm64 hosts the base image is x64 — build & run with
#      `DOCKER_DEFAULT_PLATFORM=linux/amd64` (runs under emulation).
FROM gcr.io/oss-fuzz-base/base-builder-jvm

# Put the target library jar(s) on the classpath. Either COPY a built jar in, or
# fetch a published one (build phase has network; the fuzz run does not):
#   RUN curl -fsSL -o /target.jar https://repo1.maven.org/maven2/<group>/<artifact>/<ver>/<artifact>-<ver>.jar
RUN curl -fsSL -o /target.jar \
        https://repo1.maven.org/maven2/org/yaml/snakeyaml/1.30/snakeyaml-1.30.jar

COPY Fuzzer.java /Fuzzer.java
RUN javac -encoding UTF-8 -cp "$JAZZER_API_PATH:/target.jar" -d / /Fuzzer.java

# /fuzzer wrapper drives Jazzer the OSS-Fuzz way and accepts the libFuzzer flags
# run_fuzz.sh passes (-max_total_time, -artifact_prefix, a corpus dir).
# --instrumentation_includes keeps coverage + bug detectors on the target packages.
RUN printf '#!/bin/bash\nexec /usr/local/bin/jazzer_driver \
  --agent_path=/usr/local/bin/jazzer_agent_deploy.jar \
  --cp=/:/target.jar --target_class=Fuzzer \
  --jvm_args="-Xmx2048m:-Xss1024k" "$@"\n' > /fuzzer && chmod +x /fuzzer
