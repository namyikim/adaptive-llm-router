# 저장된 L2/L3 응답 재검증 — 2026-10-27

## 실제 검증 결과

기존 유료 실행 [#40468990139](https://github.com/namyikim/adaptive-llm-router/actions/runs/40468990139)의 응답을 그대로 재사용했습니다. 새 검증 [#40472981266](https://github.com/namyikim/adaptive-llm-router/actions/runs/40472981266)은 **모델 API를 호출하지 않고**, 정규화 후보를 각각 별도 Docker 환경에서 검사했습니다.

| 단계 | L2 (저장된 Sonnet 응답) | L3 (저장된 Opus 응답) |
| --- | --- | --- |
| 원래 응답의 엄격한 형식 검사 | 통과 | 거부 — 원래 결과 유지 |
| 이번 형식 정규화 | 코드 블록 분리, 줄 수 변경 없음 | 설명/코드 블록 분리, 헤더 줄 수 10/11 → 11/12 |
| 원래 buggy 코드의 테스트 | AttributeError로 실패, exit 1 | AttributeError로 실패, exit 1 |
| 공식 fixed 코드의 동일 테스트 | 1건 통과, exit 0 | 1건 통과, exit 0 |
| 정규화 후보 적용 검사/적용 | 각각 exit 0 | 각각 exit 0 |
| 정규화 후보의 test_imap | **1건 통과, exit 0** | **1건 통과, exit 0** |

결과 아티팩트: `archived-normalized-replay-40472981266`, ID `12719437728`, ZIP SHA-256 `75db4f748145d205b5c9b2aefc773753f42b182be36e7927cb0d45d270679f62`.

두 후보의 추가 코드는 모두 `self.total = total`입니다. 이번 검증에서 L3 헤더는 `@@ -735,10 +735,11 @@`에서 `@@ -735,11 +735,12 @@`로 정규화됐습니다. **시작 위치 735와 모든 추가·삭제·문맥 줄은 그대로**이며, 변경 전후 본문 해시가 같습니다. L2와 L3 모두 동일한 정규화 정책을 거쳤습니다.

이것은 L3 원본이 엄격한 패치 형식을 준수했다는 뜻이 아닙니다. **원본 형식 판정과 형식 보정 후 코드의 테스트 성적은 별도입니다.** `original_verified_patch_success`는 L2 `true`, L3 `null`을 그대로 보존하고, `normalized_regression_passed`만 두 모델 모두 `true`로 기록합니다.

## 안전한 구분

- 기존 `model_diff.py`, 유료 호출 파이프라인과 기본 판정 정책은 변경하지 않았습니다.
- 새 `model_diff_normalization.py`는 명시적 승인 시 하나의 닫힌 코드 블록과 기존 본문으로부터 헤더의 줄 수만 재계산합니다. 코드를 추측해 채우거나 패치 위치를 옮기지 않습니다. 모호한 여러 패치, 잘못된 본문, 허용되지 않은 파일 수정은 거부합니다.
- 헤더 줄 수 보정은 모델이 의도한 내용을 모두 썼다는 증명이 아닙니다. 제공된 본문을 후보로 삼는 **보조 평가 방식**이며, 실제 Git 적용 검사와 독립적인 회귀 테스트가 여전히 필수입니다.
- 새 레코드의 `evaluation`은 `normalized_saved_response_regression_only`입니다. 기존 6건 비교기에 넣어도 원본 성적에 포함되지 않도록 테스트했습니다. 이번 재검증의 원본 비교기 완성 쌍 수는 0입니다.
- 원본 응답과 새 패치의 SHA-256, 보정한 헤더, 변경하지 않은 본문의 SHA-256, buggy/fixed/candidate 로그를 모두 남겼습니다.

## 실행 및 결과 파일

전용 워크플로 `Archived BugsInPy format-assisted replay (no model API)`는 저장된 이 한 실행의 두 응답만 재사용합니다. 새 유료 키가 필요 없고 모델 재호출 기능도 없습니다. 개발 중 요청된 검증을 위해 한 번 사용한 브랜치 자동 트리거는 main 병합 전에 제거합니다. 배포된 워크플로는 수동 실행만 가능하고 `execute=false`가 기본값입니다.

```bash
PYTHONPATH=src python -m adaptive_llm_router.bugsinpy_saved_pair_replay \
  --archive-file tests/fixtures/run_40468990139_responses.json \
  --output-root outputs/new-normalized-replay \
  --workspace /tmp/replay-workspaces \
  --dataset-root /tmp/BugsInPy
```

위 기본 명령은 정규화와 출처 검증만 수행합니다. 기존 Python 3.6 Docker 이미지와 공개 BugsInPy 메타데이터를 준비하고 `--execute`를 명시해야 실제 코드를 격리 실행합니다. 새로운 비어 있는 결과 폴더를 사용하며 기존 원본을 덮어쓰지 않습니다. Docker는 기존 verifier의 네트워크 차단, 읽기 전용 마운트, 비특권 사용자, CPU/메모리/PID 제한을 그대로 사용합니다.

결과는 `normalized_replay_summary.json`, `l2_normalized.diff`, `l3_normalized.diff`, `*_original_response.txt`, `assisted_verifier_records/`에 저장합니다. 마지막 폴더에는 각 모델의 JSON 및 원래 버그/공식 수정/후보 테스트 로그가 있습니다.

## 해석과 다음 단계

이번 `tqdm-6`의 회귀 테스트에서는 **두 모델의 수정 내용 모두 유효했습니다.** L2는 원래 형식으로도 성공했고, L3는 출력 형식 보정이 필요했습니다. 전체 테스트, 다른 버그, 일반적인 Kev 라우팅 품질, 비용 우위는 이 한 사례로 판단하지 않습니다. 공개 과거 버그에 대한 모델 기억 가능성도 남아 있습니다.

같은 `tqdm-6`로 새 유료 API 요청을 반복할 필요는 없습니다. 이후 모델 비교는 다른 사례와 더 넓은 회귀 테스트를 사용하고, 원본 응답 성적과 보조 평가 성적을 계속 나누어 기록해야 합니다. 이 변경은 새 모델 호출을 시작하지 않았습니다.
