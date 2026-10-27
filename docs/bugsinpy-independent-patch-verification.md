# 독립적 L2/L3 후보 패치 검증 — 준비 단계

앞서 검증한 6개 BugsInPy 버그를 L2·L3 대상 모델이 실제로 고칠 수 있는지 평가하기 위한 **패치 검증기**입니다. 현재는 모델 호출을 하지 않습니다. 후보 패치를 받아 **실행 가능 여부와 버그 수정 성공 여부를 독립적으로 확인하는 테스트 실행기**만 구현했습니다.

## 사용법

기본 동작은 안전한 **드라이런**입니다. 로컬 Docker 또는 일회성 격리 러너에 Python 3.11, git, 검토한 기존 Docker 이미지가 필요합니다.

```bash
git clone --depth 1 https://github.com/soarsmu/BugsInPy.git /tmp/BugsInPy

# 예시: 외부 L2/L3에서 받은 실제 후보 패치 파일을 별도로 보관.
# patch.diff를 AI가 만들었다고 이 검증기가 자동으로 증명하지는 않습니다.
PYTHONPATH=src python -m adaptive_llm_router.bugsinpy_patch_verify \
  --dataset-root /tmp/BugsInPy \
  --workspace /tmp/bugsinpy-patch-workspace \
  --output-root outputs/patch-evaluation/tornado-6/l2-attempt-1 \
  --case-id tornado-6 \
  --patch-file /tmp/candidates/tornado6-l2.patch

# 테스트 코드를 실행할 때만 --execute를 추가.
# 사전에 docker/bugsinpy-py37.Dockerfile -> adaptive-bugsinpy:py37
# 이미지를 만들어야 하며, 테스트 실행 중에는 네트워크가 차단됩니다.
```

L3도 **동일한 버그 커밋, 동일한 테스트**에 대해 별도 후보 패치 파일과 결과 폴더에서 실행해야 합니다. 패치 파일은 UTF-8 Git unified diff 형식이며, 가능한 수정 경로를 코드 내 `PATCH_TARGETS`로 고정했습니다. **GitHub 작업 디렉터리나 기존 historical buggy/fixed 체크아웃은 수정하지 않고** 별도 임시 체크아웃 사본에서 패치를 적용합니다.

## 성공 판정 조건

1. SHA로 고정한 원래 **buggy** 코드에, 고정된 **검증용 테스트 파일**만 적용한 환경에서 실제 `test_failure`가 있어야 합니다.
2. 후보 패치를 **동일한 buggy 커밋에만** 적용합니다. 실제 공식 수정 코드는 사용하지 않습니다.
3. 동일한 검증용 회귀 테스트를 후보 코드에 실행하여 모든 테스트가 통과해야 합니다.
4. 단 한 개라도 테스트를 수집할 수 없거나, 의존성·환경 오류·타임아웃 또는 불분명한 종료가 있으면 `verified_patch_success=null`로 기록합니다. 원래 버그 코드에서 재현되지 않은 경우에도 성공으로 인정하지 않습니다.
5. 실제 테스트에서 패치가 통과하면 `patch_passed`, 원래 버그가 재현되는데도 패치 후 테스트가 실패하면 `patch_failed`, 기타 오류는 별도 상태로 기록합니다.

**주의:** 통과는 해당 검증 테스트에 한정됩니다. 모든 부작용이 없음을 입증하지는 않습니다. 추가 회귀 테스트·정적 검사·반복 실행으로 강화해야 합니다.

## 경로 및 보안 제한

- `tqdm-6`: `tqdm/_tqdm.py`
- `tornado-5,7,14`: `tornado/ioloop.py`
- `tornado-6`: `tornado/ioloop.py` 또는 `tornado/platform/asyncio.py`
- `tornado-11`: `tornado/http1connection.py`

파일 추가/삭제, 경로 이동, 심볼릭링크·서브모듈·바이너리 패치, 그 외 경로 변경은 거부합니다. 검증 시 `docker_test()`의 네트워크 차단, 읽기 전용 소스 마운트, 권한 축소 및 자원 제한을 재사용합니다. 패치 내용은 신뢰할 수 없는 코드이므로 **GitHub-hosted 일회성 러너 또는 적절히 격리된 별도 머신**에서만 실행하고, 개인 PC나 운영 서버에서 실행하지 마세요.

## 결과 포맷

`candidate_patch_verification.json`에는 사례, 원래 버그 커밋, 후보 패치 SHA-256/변경 경로, 테스트별 결과·로그 이름, `baseline_status`, `candidate_status`, `verified_patch_success`가 기록됩니다. 후보가 실제 LLM이 생성한 것인지 또는 모델별 사용 비용은 자동 확인하지 않습니다. 이 값은 별도 API 호출 기록과 함께 검증해야 합니다.

이 도구 자체는 **L2/L3 API를 호출하지 않고**, 기존 6개 역사적 재현 증거를 모델의 수정 성능 측정값으로 변환하지도 않습니다.

참고: [여섯 역사적 검증 사례](bugsinpy-six-verified-historical-cases.md), [기존 독립 평가 로직](../src/adaptive_llm_router/benchmark_verified.py).
