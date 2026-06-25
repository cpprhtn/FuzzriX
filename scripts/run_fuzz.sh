#!/usr/bin/env bash
# FuzzriX — build a fuzz image and run it under resource caps (BYOD: everything in Docker).
#
# Usage:
#   bash run_fuzz.sh <build-dir> <out-dir> [seconds] [options]
#
#   <build-dir>   directory containing the Dockerfile + harness + source (build context)
#   <out-dir>     host dir for corpus + crashes (created if missing); mounted at /out
#   [seconds]     max wall-clock fuzzing time (default 120)
#
# Options (env or flags):
#   --image NAME      image tag to build (default: fuzzrix-<build-dir-basename>)
#   --binary PATH     fuzzer binary path inside the container (default: /fuzzer)
#                     NOTE: must live OUTSIDE /out — this script bind-mounts the
#                     host out-dir over /out, which masks anything built into it.
#   --memory SIZE     docker --memory (default: 3g). libFuzzer's -rss_limit_mb is
#                     derived ~1GB below this so it emits a clean oom-* artifact
#                     instead of Docker OOM-killing the container (no artifact).
#   --cpus N          docker --cpus (default: 2)
#   --dict FILE       libFuzzer -dict (path inside the build context, copied in)
#   --no-build        skip docker build (image already exists)
#   --network         allow network (default: --network=none)
#
# Self-healing note: this script does NOT fix build errors — that's the agent's job. On build failure it
# prints the log path and exits non-zero so the agent can read it, edit, and re-run. See
# references/self-healing.md.
set -euo pipefail

err() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
info() { printf '\033[36m[fuzzrix]\033[0m %s\n' "$*" >&2; }

[ $# -ge 2 ] || err "usage: run_fuzz.sh <build-dir> <out-dir> [seconds] [options]"

BUILD_DIR="$1"; OUT_DIR="$2"; shift 2
SECONDS_CAP=120
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then SECONDS_CAP="$1"; shift; fi

IMAGE=""; BINARY="/fuzzer"; MEMORY="3g"; CPUS="2"; DICT=""; DO_BUILD=1; NET="--network=none"
while [ $# -gt 0 ]; do
  case "$1" in
    --image)   IMAGE="$2"; shift 2;;
    --binary)  BINARY="$2"; shift 2;;
    --memory)  MEMORY="$2"; shift 2;;
    --cpus)    CPUS="$2"; shift 2;;
    --dict)    DICT="$2"; shift 2;;
    --no-build) DO_BUILD=0; shift;;
    --network) NET=""; shift;;
    *) err "unknown option: $1";;
  esac
done

command -v docker >/dev/null 2>&1 || err "docker not found — FuzzriX runs everything in containers (BYOD)."
[ -d "$BUILD_DIR" ] || err "build dir not found: $BUILD_DIR"
[ "$DO_BUILD" -eq 1 ] && { [ -f "$BUILD_DIR/Dockerfile" ] || err "no Dockerfile in $BUILD_DIR"; }

[ -z "$IMAGE" ] && IMAGE="fuzzrix-$(basename "$(cd "$BUILD_DIR" && pwd)")"
OUT_DIR="$(mkdir -p "$OUT_DIR" && cd "$OUT_DIR" && pwd)"
mkdir -p "$OUT_DIR/corpus" "$OUT_DIR/crashes"

if [ "$DO_BUILD" -eq 1 ]; then
  info "building image '$IMAGE' from $BUILD_DIR ..."
  LOG="$OUT_DIR/build.log"
  if ! docker build -t "$IMAGE" "$BUILD_DIR" 2>&1 | tee "$LOG"; then
    err "docker build failed — read $LOG, fix harness/Dockerfile, re-run (see references/self-healing.md)."
  fi
fi

DICT_FLAG=""; [ -n "$DICT" ] && DICT_FLAG="-dict=/out/$(basename "$DICT")" && cp "$DICT" "$OUT_DIR/"

# Give the container a stable name so it's visible in `docker ps` while running
# and `docker ps -a` after it exits. Drop any leftover from a previous run with
# the same name so the launch doesn't collide.
CONTAINER="$IMAGE-run"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

# Derive -rss_limit_mb ~1GB below the container memory cap so libFuzzer trips its
# own clean oom-* artifact before Docker OOM-kills the container (which leaves none).
case "$MEMORY" in
  *g|*G) MEM_MB=$(( ${MEMORY%[gG]} * 1024 ));;
  *m|*M) MEM_MB=${MEMORY%[mM]};;
  *)     MEM_MB=$(( MEMORY / 1048576 ));;   # bare value = bytes (docker convention)
esac
RSS_LIMIT=$(( MEM_MB - 1024 ))
[ "$RSS_LIMIT" -lt 512 ] && RSS_LIMIT=512

info "fuzzing '$IMAGE' for ${SECONDS_CAP}s  (mem=$MEMORY rss=${RSS_LIMIT}m cpus=$CPUS net=${NET:-on})  out=$OUT_DIR"
info "container name: $CONTAINER  (watch live: docker ps | grep $CONTAINER)"
set +e
docker run --name "$CONTAINER" \
  --memory="$MEMORY" --cpus="$CPUS" --pids-limit=512 $NET \
  -v "$OUT_DIR:/out" \
  "$IMAGE" \
  "$BINARY" \
    -max_total_time="$SECONDS_CAP" \
    -rss_limit_mb="$RSS_LIMIT" \
    -timeout=25 \
    -print_final_stats=1 \
    -use_value_profile=1 \
    -artifact_prefix=/out/crashes/ \
    $DICT_FLAG \
    /out/corpus
RC=$?
set -e

CRASHES=$(find "$OUT_DIR/crashes" -type f \( -name 'crash-*' -o -name 'oom-*' -o -name 'timeout-*' \) 2>/dev/null | wc -l | tr -d ' ')
info "done (exit $RC). crash artifacts: $CRASHES in $OUT_DIR/crashes"
info "container '$CONTAINER' kept (see: docker ps -a | grep $CONTAINER). remove with: docker rm $CONTAINER"
if [ "$CRASHES" -gt 0 ]; then
  info "→ triage them: see references/crash-triage.md"
fi
exit 0
