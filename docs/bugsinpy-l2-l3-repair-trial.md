# L2 / L3 실제 수정 패치 비교 — 수동 GitHub Actions

기존 6건의 역사적 버그 재현 증거를 실제 L2·L3 생성 패치의 검증으로 연결하는 실험입니다. **기본 동작은 유료 호출 및 코드 실행을 모두 하지 않습니다.** 실제 유료 호출은 사용자가 GitHub Actions 화면에서 직접 허용할 때만 발생합니다.

## 가장 쉬운 실행

1. [BugsInPy paired L2 L3 repair trial](../.github/workflows/bugsinpy-llm-repair-trial.yml) 워크플로에서 **Run workflow**를 선택합니다.
2. 첫 사례는 `tqdm-6` 또는 `tornado-6`을 권장합니다.
3. 기본 `allow_paid=false` / `execute_verifier=false`로 실행하면 결제도 Docker 실행도 없는 계획 및 모델 ID 확인 결과만 나옵니다.
4. 실제 L2+L3 각 한 차례 후보 생성 시 `Settings → Secrets and variables → Actions`에 `ANTHROPIC_API_KEY`가 있어야 하며, 사용자가 **`allow_paid=true`**를 체크해야 합니다. 이 설정은 **최대 두 번의 유료 Anthropic Messages API 요청**을 허용합니다.
5. 후보 생성과 동시에 별도 Docker 검증을 하려면 **`execute_verifier=true`**도 체크합니다. 두 체크 모두 설정해야 해당 절차가 시작됩니다.
6. Actions에서 내려받은 `bugsinpy-repair-trial-<run-id>` 아티팩트를 확인합니다.

## 고정된 실험 조건

| 구분 | 내용 |
| --- | --- |
| 케이스 | 독립 검증된 6개 사례만 허용 |
| 비교 | L2 / L3 각각 1회, 동일한 프롬프트 |
| 모델 설정 | `configs/analysis_models.json`의 `l2`, `l3` ID |
| 정답 유출 | 공식 수정 구현, fixing diff, 검증용 회귀 테스트의 소스는 모델에 전달하지 않음 |
| 프롬프트 데이터 | 버그 발생 커밋의 구현 코드 일부 + 과거 확인된 오류 메시지 |
| 경로 선택의 한계 | 수정 파일 위치는 역사적 fixing diff 리뷰에 근거한 **oracle-assisted** 탐색. 블라인드 벤치마크가 아님 |
| API 상한 | 사례당 L2 한 번 + L3 한 번; 각 최대 4096 출력 토큰 설정 |
| 검증 | 수정 전 동일 회귀 테스트 실패 → AI 패치 적용 후 전체 대상 회귀 테스트 통과 |
| 실행 격리 | GitHub-hosted 임시 머신, Docker `--network=none`, 읽기 전용 코드, 권한/CPU/메모리 제한 |
| 비용 | 실제 입력·출력 토큰은 기록하지만 단가가 검증되지 않아 **USD 비용은 `null`**로 저장 |

## 결과 위치

`outputs/repair-trials/<case_id>/trial_summary.json`에 두 모델의 요청 ID, 응답 모델 ID, 모델 ID 일치 여부, API 벽시계 시간, 토큰 수, 패치 SHA-256, 독립 검증 결과가 남습니다. 응답 모델 ID가 요청한 ID와 일치하지 않으면 **모델별 성공을 주장하지 않고 검증도 건너뜁니다.**

모델이 정상적인 Git unified diff를 반환하면 `l2_candidate.diff` 또는 `l3_candidate.diff`가 저장됩니다. 검증 허용 시 각 모델별 `<tier>_verifier/candidate_patch_verification.json`과 테스트 로그가 남습니다. API 비밀키는 결과 파일에 저장되지 않습니다. 생성된 패치·로그는 공개 역사적 코드지만, Actions 아티팩트의 노출 범위를 확인하십시오.

결과 상태는 다음과 같이 구분합니다.

- `plan_only`: 비유료 계획만 표시, LLM 호출 없음
- `generated_valid_diff`: 패치 형식을 검사했지만 버그 수정 성공은 아직 확인되지 않음
- `candidate_failed`: API 오류 또는 패치 검사 실패, 성공으로 세지 않음
- `model_identity_mismatch`: 모델 신원 미확인, 해당 모델 결과를 통과로 세지 않음
- `patch_passed` / `patch_failed`: 기존 독립 검증기의 실제 테스트 기반 판정
- `inconclusive_candidate` / `unverified_baseline` 등: 테스트 환경 문제 또는 버그 재현 실패이므로 정확도 산출에서 제외

**중요:** GitHub Actions가 성공해도 생성 패치가 버그를 고친 것은 아닙니다. `verified_patch_success=true`를 확인해야 해당 회귀 테스트 기준으로 해결됐다고 말할 수 있습니다. 동일 여섯 사례만으로 전체 모델 라우팅 정확도를 추정하면 안 됩니다.

## 개발 상 주의점

- 실제 LLM 호출은 서비스 이용 요금이 발생합니다. **이 PR이나 CI 테스트에서는 호출하지 않습니다.**
- 요청 제한 초과·API 인증 오류 등은 공급자의 오류 종류만 기록하고 민감한 HTTP 본문은 저장하지 않습니다.
- `max_tokens`는 모델별 응답 길이의 상한이며 비용 상한(USD)은 아닙니다.
- 임시 GitHub-hosted Runner에서만 오래된 프로젝트/AI 생성 코드를 실행하세요. 컨테이너 보안은 절대적인 격리 보장을 의미하지 않습니다.
- 결과가 확보되면 케이스별 실제 L2·L3 해결률, 전체 지연시간, 확인된 실제 청구 비용을 사용해 `benchmark_verified.py`로 확장하는 것이 다음 단계입니다.

관련 코드: `src/adaptive_llm_router/bugsinpy_repair_trial.py`, `src/adaptive_llm_router/bugsinpy_patch_verify.py`.
