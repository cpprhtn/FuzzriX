# FuzzriX

[English](README.md) · **한국어**

**AI 기반 범용 퍼징 가속기 — LLM을 "퍼징 엔지니어 + 크래시 분석가"로.**

> 퍼징은 우리가 가진 가장 강력한 버그 탐지 기법이지만, 그 안에서 LLM의 역할은 잘못 설정돼 왔습니다.
> 모델에게 *코드를 읽고 버그를 지목하라*고 시키는 방식은 환각에 취약하고 정밀도가 낮습니다. FuzzriX는
> 대신 LLM을 **퍼징 엔지니어 + 크래시 분석가**로 둡니다: ① 타겟에 맞는 퍼저를 알려진 퍼징 이론에서
> **합성**하고, ② 결정론적 엔진이 찾아낸 크래시의 **근본 원인을 분석**합니다. LLM은 퍼저를 만들고
> 크래시를 설명할 뿐, **버그 탐지 자체는 하지 않습니다.**

AI 에이전트를 레포에 붙이면 FuzzriX가 **실제 퍼저를 세우고, 격리된 환경에서 실행하고, 트리아지된
크래시를 가져옵니다** — 각 크래시마다 재현 입력, 근본 원인 라인, 수정안과 함께.

## 설치

FuzzriX는 **Claude Code**와 **Codex**에서 쓸 수 있는 에이전트 스킬로 배포됩니다.

### Claude Code

```bash
git clone https://github.com/cpprhtn/FuzzriX.git
ln -s "$(pwd)/FuzzriX" ~/.claude/skills/fuzzrix
```

그다음 Claude Code에서: *"이 프로젝트 퍼징해줘"* / *"파서에 libFuzzer 붙여줘"* / *"퍼징 돌려줘"*.

### Codex / 기타 에이전트

레포를 에이전트에 가리키면 [AGENTS.md](AGENTS.md) → [SKILL.md](SKILL.md)를 읽고 같은 플레이북을 따릅니다.

## 요구사항

- Docker (모든 빌드/퍼징이 컨테이너에서 일어남).
- 헬퍼 스크립트용 Python 3 (`scripts/scan_targets.py`).
- 스킬을 지원하는 에이전트(Claude Code) 또는 `AGENTS.md`(Codex).
- *선택:* 더 정밀한 퍼징 표면 추출을 위한 `tree-sitter` Python 바인딩(없으면 정규식 휴리스틱으로 폴백).

## 왜 이렇게 나누는가

LLM을 강한 곳에 두고 약한 곳에서 뺍니다:

| 단계 | 담당 | 이유 |
|---|---|---|
| **합성** (전) | LLM = 엔지니어 | 알려진 퍼징 이론(structure-aware·differential·stateful·dictionary)을 타겟별 harness/전략 코드로 옮기는 건 LLM이 잘하는 생성 작업입니다. |
| **탐지** | 결정론적 엔진 (libFuzzer / AFL++ / …) | 버그를 찾는 건 커버리지 기반 퍼저가 *그러라고 만들어진* 일 — 재현 가능, 환각 없음. **LLM은 이 루프에서 빠집니다.** |
| **분석** (후) | LLM = 분석가 | 근본 원인 추론은 ground truth(sanitizer 출력 + 소스 + 재현 입력) 위에서 돌아가므로 정밀도가 높습니다 — LLM이 가장 잘하는 산출물. |

## 무엇이 다른가

- **LLM은 퍼징 엔지니어 + 분석가이지, 버그 탐지기가 아닙니다 — BYOK 없음.** FuzzriX는 **스킬**입니다:
  이미 돌고 있는 에이전트(Claude Code, Codex, …)가 *곧 모델*입니다. harness/전략을 합성하고, 컴파일
  에러를 읽어 고치고, 각 크래시를 분석합니다 — 하지만 **탐지는 결정론적 엔진이 하고 LLM은 그 루프 밖**입니다.
- **호스트 오염 제로 (BYOD).** 모든 툴체인과 빌드는 **Docker 안**에서 돌아갑니다. 호스트는 소스 파일과
  크래시 아티팩트만 봅니다.
- **자가 치유 빌드.** 합성된 harness는 첫 시도에 컴파일되는 일이 드뭅니다. FuzzriX는 `stderr`를 잡아
  에이전트에게 되먹이고 다시 빌드합니다 — 될 때까지(또는 안 되는 이유를 정직히 보고할 때까지)의 유한 루프.
- **평가 가능 설계.** 모든 실행이 지표(빌드 성공률, time-to-first-crash, 근본원인 정확도, dedup)를
  내도록 구성돼 있어, 주장을 분위기가 아니라 숫자로 뒷받침합니다.

## 무엇을 얻는가

```
퍼저 합성 (전략 + harness + Dockerfile) → 빌드 & 자가치유
   → 결정론적 엔진 실행 (캡 적용) → 크래시 분석 (근본원인 + 수정 + 회귀 테스트)
   → 리포트 + 지표
```

레포에 남는 **재사용 가능한 타겟 맞춤 퍼저** + 랭크·트리아지된 크래시 리포트 — 각 크래시마다 재현 입력,
근본원인 라인, CWE 분류, 수정안, 회귀 테스트. 평가용 기계가독 지표까지. (*"코드 읽고 짚은 버그 목록"이
아닙니다.*)

## 안전

FuzzriX는 **본인이 소유했거나 테스트 권한이 있는 코드**를 **샌드박스 안에서** 퍼징합니다 — 라이브
프로덕션 서비스나 원격 호스트는 절대 아닙니다. 타겟 코드는 Docker 안에서만 실행하며 CPU/RAM/디스크/시간을
캡합니다. [references/authorization.md](references/authorization.md) 참고.

## 상태

**v0.6.0.** 핵심 명제는 *"LLM = 퍼징 엔지니어 + 크래시 분석가"*. 현재 동작: Docker 격리 엔진, 자가치유
빌드, 멀티 스택 harness 합성(C/C++ · Python/Atheris · Rust/cargo-fuzz), 비단순 harness 형태(round-trip ·
differential · stateful · checksum-gate), 전략 선택, 코퍼스 관리, 커버리지 개선 루프 — 무거운 분야
(crypto/TLS, media/codec)와 **실제 외부 CVE**(libxml2: 엔진이 과거 heap-overflow를 재발견, 분석가가
정확한 함수+CWE 명명)에서 검증됨. 버전 이력: [CHANGELOG.md](CHANGELOG.md).

## 라이선스

[LICENSE](LICENSE) 참고.
