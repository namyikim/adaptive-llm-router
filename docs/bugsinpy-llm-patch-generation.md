# L2/L3 자동 패치 생성 — 사용자 승인형 실험

여섯 역사적 버그를 재현했지만 이는 **모델이 고쳤다는 의미가 아닙니다**. 이 단계는 우선 `tqdm-6`, `tornado-6`에 대해 동일한 과거 buggy 커밋을 읽어 공정한 입력을 만들고, 필요할 때만 실제 유료 Anthropic L2/L3 모델에 각각 **한 번씩** 호출하는 CLI입니다.

- 기본 실행은 **dry-run**으로 API 요청이나 Docker 코드를 실행하지 않습니다.
- `--allow-paid-api`를 추가하고 `ANTHROPIC_API_KEY`, 서로 다른 `--l2-model`, `--l3-model`을 **명시해야만** 유료 호출합니다.
- 실제 모델 ID는 provider 응답과 대조하고, 반환되는 Git unified diff는 기존 `inspect_patch` 검사를 통과해야 저장합니다.
- 결과물은 `prompt.txt`, `generation_report.json`, 성공한 후보의 `l2.diff`, `l3.diff`. 토큰 사용량·모델 ID·호출 시간·패치 SHA-256을 기록합니다. 금액은 임의 추정하지 않습니다.
- 공식 수정 커밋의 구현, 회귀 테스트 파일, 정답 패치는 **프롬프트에 전달하지 않습니다**. 코드 파일은 고정된 buggy SHA에서만 읽습니다.
- 이 단계의 `verified_patch_success`는 항상 `null`입니다. 반드시 별도 Docker 검증기를 실행해야 합니다.

## 실행 예시

```bash
# 공개 BugsInPy 원본 저장소에서 과거 buggy 커밋을 정확히 체크아웃해 준비합니다.
# 예: /tmp/buggy-tqdm-6 디렉터리에 실제 tqdm-6 buggy SHA 체크아웃
PYTHONPATH=src python -m adaptive_llm_router.bugsinpy_llm_patch_generate \
  --case-id tqdm-6 \
  --buggy-checkout /tmp/buggy-tqdm-6 \
  --failure-file /tmp/independent_failure_description.txt \
  --output-root outputs/llm-patch/tqdm6-dryrun

# 외부 API 호출은 의도적으로 기본 비활성화.
# 유료 실험은 본인이 지원 모델 ID·API 키·예산을 확인한 후에만:
export ANTHROPIC_API_KEY="..."
PYTHONPATH=src python -m adaptive_llm_router.bugsinpy_llm_patch_generate \
  --case-id tqdm-6 \
  --buggy-checkout /tmp/buggy-tqdm-6 \
  --failure-file /tmp/independent_failure_description.txt \
  --output-root outputs/llm-patch/tqdm6-paid-1 \
  --l2-model "EXPLICIT_SUPPORTED_MODEL_ID_L2" \
  --l3-model "EXPLICIT_SUPPORTED_MODEL_ID_L3" \
  --allow-paid-api
```

**모델 ID는 예시 값으로 자동 생성하거나 기본 설정하지 않습니다.** 모델 지원 여부·가격·호출 권한을 별도로 확인하세요. 이 코드를 GitHub Actions `workflow_dispatch`로 자동 호출하지 않으며 API 키를 커밋하지 않습니다.

모델이 만든 패치는 `src/adaptive_llm_router/bugsinpy_patch_verify.py` CLI로 별도 격리 검증을 합니다. 생성 기록과 검증 기록을 패치 SHA-256으로 연결하고, 실제 테스트 성공 여부·비용·시간을 양쪽 모델에 동일하게 측정한 뒤에만 유효한 품질 비교로 집계합니다.

초기 대상에는 검증된 기존 실패 설명을 쓰지만 **공식 수정 버전의 테스트 코드나 패치 설명이 섞이지 않도록** 입력을 검토해야 합니다. 도구는 모든 정보누수나 프롬프트 인젝션을 자동 탐지하지 못합니다.
