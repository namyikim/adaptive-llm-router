# 실제 BugsInPy 오류 재현 — 격리된 CPU 실험

기존 Kev-4B/9B 비교에서 **최종 모델 선택이 달랐던 6건**을 대상으로, BugsInPy가 제공하는 `buggy_commit_id`, `fixed_commit_id`, `run_test.sh`를 사용해 두 버전의 **실제 관련 테스트 결과**를 검증할 수 있는 실험 도구를 추가했습니다. 최초 우선순위는 `tqdm-6`과 `tornado-6`입니다.

이 실험은 Kev 모델이나 Claude를 호출하지 않습니다. **아직 버그 수정 성공률을 측정하는 실험이 아니며**, 과거 버그가 실제로 재현되는지 확인하는 선행 단계입니다.

## GitHub에서 실행하는 방법 (Colab GPU 불필요)

1. 저장소에서 **Actions → BugsInPy historical test reproduction (manual, isolated)** 워크플로를 엽니다.
2. **Run workflow**에서 사례 `tqdm-6`, `tornado-6` 또는 `all`을 선택합니다. `all`은 tqdm-6과 Tornado 5건을 뜻합니다.
3. 기본 설정 `execute = false`는 metadata만 생성하는 안전한 드라이런입니다. Docker에서 실제 테스트를 실행할 때만 **`execute = true`를 명시적으로 선택**합니다.
4. 실행 완료 후 GitHub Actions 화면의 **Artifacts**에서 `bugsinpy-reproduction-<run-id>`를 내려받습니다.
5. `reproduction_summary.json`과 개별 `tqdm-6.json`/`tornado-6.json` 및 각 테스트 출력 `.log`를 확인합니다.

**중요:** GitHub Actions 전체 작업이 성공했더라도 역사적 버그 재현에 성공한 것은 아닙니다. 반드시 각 사례의 `status`가 `reproduced_buggy_fail_fixed_pass`인지 확인해야 합니다. 다른 상태는 성공으로 치지 않습니다.

## 수행 방식과 격리

GitHub Actions 임시 Linux runner에서만 공개 BugsInPy 메타데이터를 clone하고, 검토된 Python Dockerfile로 런타임 이미지를 만듭니다. 과거 프로젝트 커밋은 호스트에 **checkout만** 하고, 테스트는 Docker에서 별도로 실행합니다. 과거 `setup.sh` 및 알 수 없는 임의 셸 명령은 실행하지 않습니다.

- `tqdm-6`: BugsInPy의 Python 3.6.9 기록에 맞춘 Python 3.6.15 이미지, pytest 5.4.3을 사용합니다. 실제 대상: `python3 -m pytest tqdm/tests/tests_synchronisation.py::test_imap`.
- `tornado-5/6/7/11/14`: 기록된 Python 3.7.0에 가까운 Python 3.7.17 이미지와 `unittest`를 사용합니다. `tornado-6`에는 두 개의 leak 테스트가 있습니다.
- 이미지 설치 단계에서는 사전 지정된 공개 패키지 다운로드가 필요할 수 있습니다. 테스트 실행 단계는 **`--network=none`**, `--read-only`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--pids-limit=128`, `--memory=2g`, `--cpus=2`, `--user=65534:65534`로 제한합니다.
- 컨테이너에서 코드/패치를 생성해 호스트 저장소에 쓰지 않습니다. 히스토리의 buggy와 fixed 커밋은 별도 읽기 전용 마운트로 실행합니다.

보안 한계: Python 3.6/3.7 및 해당 Debian 이미지는 지원이 종료된 오래된 환경이므로 일반 업무용 머신이나 장기 실행 서버에서 실행하지 마세요. GitHub-hosted 임시 runner 또는 별도의 격리 머신을 권장합니다. 이는 완전한 보안 경계나 완전 재현성을 보장하지 않습니다.

## 2026-10-27 tqdm-6: regression test added in FIXED commit

An actual `execute=true` run [#40426312505](https://github.com/namyikim/adaptive-llm-router/actions/runs/40426312505) built the legacy Python image and ran both historical commits. It returned `environment_or_timeout` **not because of a model issue or a timeout**, but because `test_imap` did not exist at the buggy commit: pytest exit code 4, `collected 0 items`, `ERROR: not found`. The same test existed in the fixed commit and passed (exit code 0). This is **not a successful buggy-fail/fixed-pass reproduction**.

Git comparison confirms the historical fix added `test_imap` to `tqdm/tests/tests_synchronisation.py` and separately modified the implementation file `tqdm/_tqdm.py`. The replay runner now explicitly identifies missing tests as `test_not_collected`, **not** as bug failures.

For **the pinned `tqdm-6` case only**, if the buggy commit lacks that exact test, the runner executes an additional, clearly labeled *test-only regression backport*: Docker read-only bind-mounts `tqdm/tests/tests_synchronisation.py` from the pinned fixed commit on top of the buggy checkout's test file. It does **not** copy `tqdm/_tqdm.py` or any implementation diff. The original no-test log remains `tqdm-6_buggy_1_missing_test.log` and the backport attempt is stored in `tqdm-6_buggy_1.log`; the case JSON records `regression_test_backport`, test SHA-256, `test_origin=fixed_commit_regression_test_only` and whether the historical buggy-fail/fixed-pass reproduction was confirmed. If the regression-test-only backport still doesn't produce a test assertion failure, status remains inconclusive.

**Leakage restriction:** The backported test comes from the fixing commit, so it is a **verifier-only oracle**. Never expose its code or the fixed implementation as target LLM debugging input, and do not use it for model comparison calibration without explicitly disclosing this test oracle.

## 2026-10-27: confirmed historical tqdm-6 failure, erroneous classifier

[Actions run #40428395903](https://github.com/namyikim/adaptive-llm-router/actions/runs/40428395903) executed `tqdm-6` with `execute=true`, on commit `ce59ea3546feb3846e5d1ad8ae7b17255203f225`. The result artifact `bugsinpy-reproduction-40428395903` contains:

| Evidence | Buggy commit | Fixed commit |
| --- | --- | --- |
| Selected `test_imap` | 1 collected | 1 collected |
| Exit code | 1 | 0 |
| Underlying outcome | **AttributeError** in `tqdm/_tqdm.py` `__len__` | **1 passed** |
| Test provenance | Verifier-only fixed-commit regression test, mounted read-only | Native fixed-commit test |

The buggy traceback reports: `AttributeError: 'tqdm' object has no attribute 'total'`. The actual source code contains `except ImportError:` in a printed source excerpt; the earlier classifier scanned for the bare word `ImportError` before checking `FAILED`, falsely recorded `environment_failure`. Consequently the on-disk `reproduction_summary.json` currently reports `verified_reproductions: 0` and `environment_or_timeout`, **but the saved underlying logs prove the historical bug failed and the official fixed version passed**. This is a **post-hoc expert assessment** and does not rewrite the existing run artifact.

The classifier now matches actual pytest/unittest result lines and real import/syntax errors, not incidental words in printed source. New CPU regression tests cover this exact trace, missing-test cases, and genuine environment failures. Rerun this workflow under the updated main branch to produce **machine-verifiable** `reproduced_buggy_fail_fixed_pass` data.

This success is **historical defect reproduction only**. No AI generated a patch and no L2-vs-L3 repair success/cost results have been measured.

## 2026-10-27: Tornado-6 false positive in run #40430425836

In [workflow #40430425836](https://github.com/namyikim/adaptive-llm-router/actions/runs/40430425836), `case_id=tornado-6`, `execute=true`, and all containers finished. The machine-produced JSON wrongly reported `reproduced_buggy_fail_fixed_pass`, `verified_reproductions=1`. Inspecting **both actual buggy logs** shows:

```text
ERROR: LeakTest (unittest.loader._FailedTest)
AttributeError: module 'tornado.test.asyncio_test' has no attribute 'LeakTest'
Ran 1 test in 0.000s
FAILED (errors=1)
```

The requested tests **never ran** on the buggy commit; two tests passed in the official fixed commit. GitHub commit comparison confirms that the entire `LeakTest` class and both tests were introduced in the fixed commit, alongside **separate implementation edits** in `tornado/ioloop.py` and `tornado/platform/asyncio.py`. The historical reproduction claim from that prior artifact is **invalid; do not use it as a verified case**.

### Safeguard and legitimate replay

The classifier now recognizes unittest `_FailedTest` with a missing module attribute as `test_not_collected`, which **cannot** count as an assertion/test failure. If this arises for the SHA-pinned `tornado-6` case only, the runner saves each original missing-test log and mounts **only** the historical fixed-commit `tornado/test/asyncio_test.py` test file over that path in the buggy checkout (read-only Docker bind mount). It does **not** copy either implementation fix. Both new regression tests are replayed separately; evidence includes `regression_test_backport`, the test SHA-256, two `*_missing_test.log` files and two replay logs. A repaired test runner should report `reproduced_buggy_fail_fixed_pass` only if a real failing assertion/error occurs *inside the newly collected test* and all fixed-commit tests pass.

**Verification-only leakage:** the new test file was authored in the fixing commit; the test code is permitted *only* to establish a historical verifier result. It must not appear in AI debugger prompts or be described as a blind no-oracle task.

The new GitHub Actions step summary displays explicit per-case statuses to prevent confusing the green job icon with a reproduced historical defect. Re-run case `tornado-6`, `execute=true` on updated main before recording any confirmed Tornado-6 reproduction.

## 상태 해석

| status | 의미 |
| --- | --- |
| `not_executed` | 드라이런; 기록만 만들고 테스트 미실행 |
| `reproduced_buggy_fail_fixed_pass` | buggy에서 테스트 실패가 확인되고 fixed에서 동일 테스트 모두 통과 |
| `not_reproduced_both_pass` | 두 버전 모두 관련 테스트 통과 |
| `test_not_collected` (개별 테스트 verdict) | 해당 커밋에서 테스트를 찾지 못함; 버그 실패로 판정하지 않음 |
| `inconclusive_tests` | 두 버전 모두 실패하는 등 정답 판정 불가 |
| `environment_or_timeout` | 의존성·import 문제, 알 수 없는 종료 또는 타임아웃 |
| `environment_unavailable` | Docker/이미지/커밋 체크아웃 자체가 실패 |

실험 결과의 `verified_historical_reproduction=true`는 **원래 버그를 재현했다는 의미**입니다. `llm_verified_success`는 `null`로 두며, 실제 LLM에 수정 패치를 생성하게 하고 **별도의 독립적인 테스트 검증을 통과했을 때만** 채워야 합니다. `benchmark_verified.py`의 실측 성공/비용 입력과 혼동하지 마세요.

과거 기록의 대상 테스트가 환경/타이밍에 따라 통과할 수 있습니다. 예를 들어 monitor/asyncio 테스트는 불안정할 수 있으며, 한번 실패했다고 버그 수정의 성공을 입증하는 것은 아닙니다. 가능하면 반복 실행 및 별도 확인이 필요합니다.

## 로컬 사용법 (Docker 설치 시에만)

```bash
git clone --depth 1 https://github.com/soarsmu/BugsInPy.git /tmp/BugsInPy
PYTHONPATH=src python -m adaptive_llm_router.bugsinpy_reproduce \
  --dataset-root /tmp/BugsInPy --workspace /tmp/bugsinpy-replay \
  --output-root outputs/reproduction --cases tqdm-6 tornado-6

# Opt-in execution: explicitly build reviewed Docker images first.
docker build -f docker/bugsinpy-py36.Dockerfile -t adaptive-bugsinpy:py36 .
docker build -f docker/bugsinpy-py37.Dockerfile -t adaptive-bugsinpy:py37 .
PYTHONPATH=src python -m adaptive_llm_router.bugsinpy_reproduce \
  --dataset-root /tmp/BugsInPy --workspace /tmp/bugsinpy-replay \
  --output-root outputs/reproduction --cases tqdm-6 tornado-6 --execute
```

CLI 실행은 CPU 기반이며 A100이나 유료 LLM 계정이 필요 없습니다. 작성된 Docker 이미지의 빌드는 네트워크 접근과 CPU 리소스를 사용합니다. 이 GitHub 코드 자체는 아직 실사용 Docker 재현 성공 결과를 주장하지 않습니다.

참고: [BugsInPy 원본](https://github.com/soarsmu/BugsInPy), [기존 100건의 모델 선택 비교](bugsinpy-paired-evaluation.md).
