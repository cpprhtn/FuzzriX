# 변경 이력

[English](CHANGELOG.md) · **한국어**

FuzzriX의 주요 변경사항을 기록합니다. 형식은 [Keep a Changelog](https://keepachangelog.com/)를 따르며,
시맨틱 버저닝을 사용합니다.

## [0.2.0] — 2026-06-24

### 추가
- **전략 선택** (`references/strategy-selection.md`) — 타겟별로 libFuzzer 노브(value_profile, dictionary,
  fork, max_len)를 결정론적이고 근거를 명시해 선택.
- **코퍼스 관리** (`references/corpus-management.md`) — 시드 주입, `-merge=1` 최소화, 실행 간 지속·재사용을
  모두 한 컨테이너 안에서.
- **커버리지 개선 루프** (`references/coverage-iteration.md`) — harness의 도달 범위를 넓히는 유한 피드백
  루프(가장 큰 성능 레버).
- **`CLAUDE.md`** — 이 레포 작업용 에이전트 가이드.
- **"Four hats" 프레임**과 **8단계 루프**(전략·커버리지 개선 단계 추가).
- **한국어 문서** (`README.ko.md`)와 "사용자 언어로 응답" 지침.
- `run_fuzz.sh`에 `-use_value_profile=1` 기본 적용(매직/길이 게이트 통과에 도움).

### 변경
- **크래시 트리아지** — `(crash_type, crash_state)` 중복 제거(dedup), security/benign 분류, severity 매핑
  (OOB 쓰기 시 한 단계 상향).
- `harness-generation`, `dockerfile-generation`, `fuzzing-run`을 정확한 libFuzzer 플래그·종료 코드 처리·
  스택별 빌드 세부로 확장.
- **README 재구성** — 설치·요구사항을 위로, 로드맵 제거(이력은 여기서 관리).

### 제거
- 옛 태그라인("Fuzz + Matrix + X", "successor to Longinus" 표현).

## [0.1.1] — 2026-06-23

### 추가
- **Docker를 hard prerequisite로** — 없으면 호스트에서 돌리지 않고 설치 안내 후 중단.
- **첫 응답 프레이밍 재설정** — "버그 찾아줘"로 불려도, 스킬은 퍼저를 만들고 엔진이 찾게 한다는 점을
  먼저 명확히.

## [0.1.0] — 2026-06-23

### 추가
- 에이전트 스킬(Claude Code + Codex)로 최초 릴리스.
- C/C++ libFuzzer MVP; 멀티 스택 지원: **Python/Atheris**, **Rust/cargo-fuzz** (Go 라우팅).
- 자가치유 빌드 루프, BYOD Docker 격리, 리소스 캡.
- harness + Dockerfile 템플릿(`cpp-libfuzzer`, `python-atheris`).
- 헬퍼 스크립트: `scan_targets.py`(퍼징 표면 식별), `run_fuzz.sh`(캡 적용 Docker 실행).
- 레퍼런스 플레이북: authorization, context extraction, harness/Dockerfile generation, self-healing,
  fuzzing run, crash triage.
