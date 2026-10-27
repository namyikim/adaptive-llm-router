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

`allow_paid_api=true`는 실제 요금이 청구되는 최대 2건의 모델 호출을 허용합니다. `execute_patch_tests=true`까지 선택하면 일회성 GitHub-hosted runner에서 역사적 Python Docker 이미지를 만들고 생성된 후보 패치만 안전 제한된 환경에서 검사합니다. **각 모델 지원 여부와 실제 요금은 실행 전 사용자 확인이 필요합니다.** 임의의 모델 ID나 가격표를 기본값으로 정하지 않았습니다. **GitHub Actions의 Re-run jobs를 누르면 유료 호출도 다시 실행되어 별도 비용이 청구될 수 있습니다.** 요청 1회당 호출은 L2/L3 각 최대 1회이고, 실행 간 중복 과금 차단 기능은 없습니다.

## Actions #40458334955의 실패 원인 및 수정 (2026-10-27)

[GitHub Actions #40458334955](https://github.com/namyikim/adaptive-llm-router/actions/runs/40458334955)는 `case_id=tqdm-6`, `allow_paid_api=true`, `execute_patch_tests=true`로 실행됐지만 **`l2_model`과 `l3_model`이 모두 빈 문자열**이어서 사전 검사에서 중단됐습니다. `ANTHROPIC_API_KEY`의 실제 등록 여부는 로그만으로 확인할 수 없습니다. 이 실행은 API 요청이나 Docker 검증 전에 중단됐기 때문에 API 요금이 발생하지 않았습니다. 결과가 생성되지 않아 아티팩트도 없습니다.

### 무료 드라이런

`Run workflow`에서 `case_id=tqdm-6`, `allow_paid_api=false`, `execute_patch_tests=false` 그대로 실행합니다. 모델 ID와 API 키가 필요하지 않습니다.

### 실제 유료 비교 (본인이 명시적으로 선택했을 경우에만)

Anthropic의 [공식 모델 목록](https://platform.claude.com/docs/en/models/overview)에서 **현재 접근 가능한 Claude API 모델 ID**를 확인한 후 다음처럼 입력할 수 있습니다.

| 필드 | 입력 예시 |
| --- | --- |
| `l2_model` | `claude-sonnet-5-5` |
| `l3_model` | `claude-opus-5-5` |
| `allow_paid_api` | `true` |
| `execute_patch_tests` | `true` — 후보 패치의 Docker 검증까지 실행하고자 할 때만 |

이는 **선택 가능한 입력 예시**일 뿐 저장소의 기본값은 아닙니다. 지정한 모델을 Anthropic API 계정에서 사용할 수 있어야 하며, ChatGPT 구독만으로 Anthropic API를 사용할 수 있는 것은 아닙니다. `ANTHROPIC_API_KEY`는 `Settings → Secrets and variables → Actions → New repository secret`에서 이름과 값을 분리해 등록하며, GitHub Actions 실행 폼에는 **절대 키를 입력하지 않습니다**.

사전검사는 이제 API 키 비어 있음, L2 ID 비어 있음, L3 ID 비어 있음, 두 ID 중복을 구분해 알려줍니다. 또한 Sonnet 5.5와 Opus 5.5는 **`temperature`, `top_p`, `top_k`를 허용하지 않으므로** API 요청에 해당 필드를 전달하지 않도록 변경했습니다. 참조: [Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview), [Opus 5.5 migration](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide).

**주의:** 유료 입력을 선택했다면 첫 실행과 GitHub Actions의 `Re-run`는 각각 새로운 청구를 발생시킬 수 있습니다. 사전 검증이 통과하더라도 지원되지 않는 모델 ID, 계정 크레딧 부족, 모델별 정책·토큰 한도 등으로 API가 실패할 수 있으며, 해당 경우에는 원시 성공률로 보정하지 않습니다.

## 결과 위치와 평가 제한

GitHub Actions 실행 화면의 `Artifacts → bugsinpy-llm-patch-eval-<run-id>`를 다운로드하면 다음 파일을 확인할 수 있습니다.

- `e2e_summary.json`: 실행 설정, 입력 SHA-256, 각 모델 ID·실제 토큰 사용량·생성 상태, 실제 패치 검증 성공 여부
- `prompt.txt`: 두 모델에 공통으로 제공된 **buggy 소스와 오류 설명**
- `l2.diff`, `l3.diff`: 검증 가능한 형식으로 반환한 후보 패치만 저장
- `verifier_results/`: **실제 Docker 검증을 명시적으로 선택한 경우에만** `tqdm-6_l2.json`/`tqdm-6_l3.json` 형태의 검증 기록과 `logs/` 폴더

`status=patch_passed`는 검증 대상 회귀 테스트에 한해 코드가 통과했다는 뜻입니다. 추가로 `six_case_comparison.json`을 기록하지만, **6건 전부 L2·L3 독립 검증이 끝나지 않았다면 전체 성공률은 `null`**로 남습니다. 

`verified_patch_success=null`이면 미검증·환경 오류·패치 생성 불가 등이므로 **성공률이나 실패율에 임의로 포함시키지 않습니다.** 두 모델 모두 독립적으로 검증된 경우에만 한 사례 내 비교가 가능하며, **한 사례로 전체 모델 우위를 주장할 수 없습니다.**

또한 이번 테스트는 본질적으로 완전한 블라인드 벤치마크가 아닙니다. **역사적 수정 위치로 사전에 알려진 구현 파일**과 **수정 커밋에서 추가한 회귀 테스트에서 관찰한 증상**을 프롬프트에 포함합니다. 다만 공식 정답 구현 내용이나 회귀 테스트 코드 자체는 프롬프트에 제공하지 않습니다. 이 특성은 `e2e_summary.json`에도 출처로 기록합니다.

더 많은 대표 문제를 충분히 수집한 뒤 기존 `bugsinpy_patch_compare.py`와 `benchmark_verified.py`로 모델별 수정 성공률·지연·실제 비용을 비교하는 것이 다음 단계입니다. 현재 통합 평가 코드는 유료 API를 실제 호출하거나 독립적인 후보 패치를 테스트한 실적이 없습니다.
