"""
법제처 API 호출 공용 유틸 — 재시도(retry) 로직 포함
=====================================================
법제처 API(www.law.go.kr/DRF/...) 호출 시 일시 장애 대응:
  - DNS 해석 실패 (NameResolutionError) — 새벽 점검 시간대 흔함
  - 연결 타임아웃 / 연결 리셋 (ConnectionResetError)
  - 5xx 서버 오류

대응 전략: 점진적 백오프(exponential backoff) — 강화판
  1차 시도 실패 → 5초 대기 → 2차 시도
  2차 시도 실패 → 15초 대기 → 3차 시도
  3차 시도 실패 → 45초 대기 → 4차 시도
  4차 시도 실패 → 90초 대기 → 5차 시도
  5차 시도 실패 → 180초 대기 → 6차 시도 (최종)
  최종 실패 시 None 반환 (호출자가 적절히 폴백)

총 최대 대기 시간: 약 5.5분 (5+15+45+90+180=335초)
이전 4회 retry(65초) 대비 강화. SSL EOF, DNS 일시 장애 등 회복 가능.

사용처: collect_full_history.py, collect_article_history.py,
       collect_attached_tables_history.py
"""

import time

import requests


# 최대 재시도 횟수 (1차 시도 + 추가 N회 재시도)
MAX_RETRIES = 5
# 백오프 시퀀스 (초) — attempt 0,1,2,3,4 에 매핑
BACKOFF_SECONDS = [5, 15, 45, 90, 180]


def request_xml_with_retry(url: str, params: dict, timeout: int = 90) -> requests.Response | None:
    """
    법제처 API GET 호출을 재시도와 함께 수행한다.

    성공 시 Response 객체 반환, MAX_RETRIES 회 모두 실패 시 None 반환.
    호출자는 None 반환 시 해당 항목을 "조회 실패"로 처리하고 다음으로 진행할 수 있다.

    timeout 60→90초 증가: 새벽 시간대 응답 지연 흡수.
    """
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=timeout,
                                headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            if attempt > 0:
                print(f"    ✅ 재시도 성공 (시도 {attempt + 1}/{MAX_RETRIES + 1})")
            return resp
        except requests.RequestException as e:
            last_error = e
            if attempt < MAX_RETRIES:
                wait = BACKOFF_SECONDS[attempt]
                err_type = type(e).__name__
                print(f"    ⚠️ API 호출 실패 ({err_type}, 시도 {attempt + 1}/{MAX_RETRIES + 1}) "
                      f"— {wait}초 후 재시도")
                time.sleep(wait)
            else:
                print(f"    ❌ 최종 실패 ({MAX_RETRIES + 1}회 시도): {last_error}")
                return None
    return None
