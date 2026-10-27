# BugsInPy L2 vs L3 — 단일 실행 통합 평가

기존에 검증한 `tqdm-6`, `tornado-6` 버그를 대상으로 **실패 증상 및 buggy 코드 확인 → L2/L3 생성 요청 → 후보 패치 검사 → 격리 테스트 → 결과 보관**을 하나의 수동 GitHub Actions 워크플로로 연결합니다. 기존 6건 모두에 대한 전체 평가가 아니라 **초기 2개 사례 중 한 건씩 선택**하는 파일럿입니다.

## 실행 화면

[GitHub Actions: BugsInPy L2-vs-L3 patch evaluation (opt-in)](https://github.com/namyikim/adaptive-llm-router/actions/workflows/bugsinpy-llm-eval.yml)

`Run workflow`에서 다음을 설정합니다.

| 입력 | 드라이런 기본값 | 의미 |
| --- | --- | --- |
| `case_id` | `tqdm-6` | `tqdm-6` 또는 `tornado-6` |
| `allow_paid_api` | `false` | `true`일 때만 Anthropic API를 L2·L3 각각 최대 한 번 호출 |
| `execute_patch_tests` | `false` | `true`일 때만 모델 패치를 Docker에서 테스트. `allow_paid_api=true`도 필수 |
| `l2_model` / `l3_model` | 빈 값 | 유료 사용 시 실제 접근 가능한 **서로 다른** Anthropic 모델 ID를 직접 지정 |

**가장 먼저 권장하는 실행은 기본값 그대로인 무료 드라이런입니다.** 공개 BugsInPy 메타데이터와 고정된 buggy 커밋을 읽고, 동일한 L2/L3 입력 `prompt.txt`와 `e2e_summary.json`을 아티팩트에 저장합니다. 과거 프로젝트 설정 스크립트나 모델 API, Docker 테스트 코드는 실행하지 않습니다.

유료 모델 호출을 직접 선택하려면 GitHub 저장소의 **Settings → Secrets and variables → Actions**에 본인의 `ANTHROPIC_API_KEY` secret이 설정돼 있어야 합니다. 절대 GitHub 이슈·커밋·워크플로 설정 입력칸에 API 키 자체를 입력하지 마세요. 설정된 키가 없어도 유료 호출을 시도하지 않고 중단합니다.

`allow_paid_api=true`는 실제 요금이 청구되는 최대 2건의 모델 호출을 허용합니다. `execute_patch_tests=true`까지 선택하면 일회성 GitHub-hosted runner에서 역사적 Python Docker 이미지를 만들고 생성된 후보 패치만 안전 제한된 환경에서 검사합니다. **각 모델 지원 여부와 실제 요금은 실행 전 사용자 확인이 필요합니다.** 임의의 모델 ID나 가격표를 기본값으로 정하지 않았습니다.

## 결과 위치와 평가 제한

GitHub Actions 실행 화면의 `Artifacts → bugsinpy-llm-patch-eval-<run-id>`를 다운로드하면 다음 파일을 확인할 수 있습니다.

- `e2e_summary.json`: 실행 설정, 입력 SHA-256, 각 모델 ID·실제 토큰 사용량·생성 상태, 실제 패치 검증 성공 여부
- `prompt.txt`: 두 모델에 공통으로 제공된 **buggy 소스와 오류 설명**
- `l2.diff`, `l3.diff`: 검증 가능한 형식으로 반환한 후보 패치만 저장
- `verification_l2/`, `verification_l3/`: **실제 Docker 검증을 명시적으로 선택한 경우에만** 개별 테스트 로그와 `candidate_patch_verification.json`

`status=patch_passed`는 검증 대상 회귀 테스트에 한해 코드가 통과했다는 뜻입니다. `verified_patch_success=null`이면 미검증·환경 오류·패치 생성 불가 등이므로 **성공률이나 실패율에 임의로 포함시키지 않습니다.** 두 모델 모두 독립적으로 검증된 경우에만 한 사례 내 비교가 가능하며, **한 사례로 전체 모델 우위를 주장할 수 없습니다.**

또한 이번 테스트는 본질적으로 완전한 블라인드 벤치마크가 아닙니다. **역사적 수정 위치로 사전에 알려진 구현 파일**과 **수정 커밋에서 추가한 회귀 테스트에서 관찰한 증상**을 프롬프트에 포함합니다. 다만 공식 정답 구현 내용이나 회귀 테스트 코드 자체는 프롬프트에 제공하지 않습니다. 이 특성은 `e2e_summary.json`에도 출처로 기록합니다.

더 많은 대표 문제를 충분히 수집한 뒤 기존 `bugsinpy_patch_compare.py`와 `benchmark_verified.py`로 모델별 수정 성공률·지연·실제 비용을 비교하는 것이 다음 단계입니다. 현재 통합 평가 코드는 유료 API를 실제 호출하거나 독립적인 후보 패치를 테스트한 실적이 없습니다.
