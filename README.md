# 도로교통법 한눈에

법률 · 시행령 · 시행규칙 · 별표를 조문 단위로 통합 비교하고 개정 연혁을 한 화면에서 추적하는 뷰어.

## 사용법

### 온라인 (GitHub Pages)

GitHub 저장소에서 Pages를 활성화하면 바로 사용 가능합니다. 별도 설치 불필요.

> 예: `https://<사용자명>.github.io/<저장소>/viewer.html?jo=44`
> `?jo=44` 같은 쿼리로 특정 조문 직접 링크 가능 (예: 제44조 음주운전).

### 로컬 테스트

`viewer.html`은 외부 데이터 파일(`web_data/*.js`)을 `<script>`로 로드하므로 더블클릭(`file://`)으로 열면 브라우저 보안(CORS) 때문에 작동하지 않습니다. 로컬에서 보려면 간단한 HTTP 서버를 띄우세요.

```bash
python serve.py
```

브라우저가 자동으로 `http://localhost:8000/viewer.html` 을 엽니다. 종료는 Ctrl+C.

## 핵심 기능

- **3단 비교**: 법률 조문 → 위임 근거 시행령 → 시행규칙·별표를 한 화면에 통합
- **연혁 추적**: 조문이 언제·왜·어떻게 바뀌었는지, 함께 변경된 시행령·시행규칙·별표까지 자동 매핑
- **별표 PDF 좌우 비교**: 개정 직전·직후의 별표 PDF를 한 화면에서 좌우로 비교 (예: 운전면허 행정처분 기준)
- **키워드 검색**: 본문(항·호 포함) 검색. 매칭 위치 미리보기.
- **딥링크**: `?jo=44&tab=history` 쿼리로 특정 조문/탭 URL 공유 가능

## 데이터 출처

- 국가법령정보센터 OPEN API: <https://www.law.go.kr/DRF/>

## 빌드 (자료 업데이트)

법령이 새로 개정되면 한 줄로 모든 단계가 순차 실행됩니다 (10단계, 처음 ~30분 / 증분 갱신 ~수 분):

```bash
python update_all.py
```

옵션:

```bash
python update_all.py --skip-collect   # API 수집 건너뛰고 빌드만 (data/ 이미 있을 때)
python update_all.py --no-pdfs        # 별표 PDF 다운로드 건너뛰기 (가벼운 테스트)
```

수동으로 한 단계씩 실행하려면 각 스크립트를 직접 호출 (`build_3tier_map.py` → `collect_full_history.py` → ... → `generate_viewer.py`).

증분 업데이트 시 PDF 다운로드는 폴더에 없는 신규 시점만 받아 빠릅니다 (~수 초).

## 자동 갱신 (GitHub Actions)

매주 월요일 새벽 05:00 KST에 `update_all.py`가 GitHub 서버에서 자동 실행되어 데이터를 갱신하고 사이트에 배포합니다 (`.github/workflows/update.yml`). 사용자 PC와 무관하게 GitHub이 자기 서버에서 실행하므로 별도 조작이 필요 없습니다.

`actions/cache`로 직전 실행의 `data/` 폴더(빌드 산출물)를 복원하여 신규 공포건만 추가 수집합니다. 첫 실행만 풀스캔(약 60분)이며 이후 매주 갱신은 5~10분 안에 끝납니다.

**API 장애 대응**: 법제처 API 호출에 자동 재시도(5초/15초/45초 간격) 적용. DNS 일시 장애·연결 리셋 등 일과성 오류는 자동 복구합니다 (`api_utils.py`).

**회귀 방지 검증**: commit 전에 자동으로 다음을 점검하고, 하나라도 실패하면 commit하지 않고 실패 알림만 보냅니다.

- 핵심 파일 존재 + 크기 (`viewer.html`, `web_data/data_core.js` 등)
- `docs.google.com/gview` 부재 (모바일 PDF 회귀 차단)
- `web_data/pdfjs/web/viewer.html` 경로 존재 (PDF.js 자체 호스팅 보장)
- `tblHistoryData` 폴백 코드 존재

**알림**: 변경사항이 있을 때(또는 검증 실패 시) 저장소에 GitHub Issue가 자동 생성되며, 등록된 메일로 알림이 전송됩니다. Issue 제목에 `[클로드 코드가 회신]` prefix가 붙어 정상 알림임을 식별할 수 있습니다.

**수동 트리거**: GitHub 저장소 → Actions 탭 → "매주 자동 갱신" → "Run workflow" 버튼으로 즉시 실행 가능합니다.

## 구조

```
viewer.html              # 가벼운 본체 (~85KB)
serve.py                 # 로컬 테스트용 HTTP 서버
web_data/                # 분리된 데이터 (총 ~110MB)
  data_core.js           # 매핑·조문·캐스케이드·전후비교
  data_timeline.js       # 조문별 타임라인
  data_tbl_diff_*.js     # 별표 전후비교 (시행령/시행규칙)
  data_tbl_pdf.js        # 별표 최신 공포일자 매핑
  data_tbl_history.js    # 별표/서식 history 슬림판 (옛 시점 별지 폴백용)
  pdfjs/                 # 자체 호스팅 PDF.js viewer (모바일 PDF 렌더링)
data/
  table_pdfs/            # 별표 시점별 PDF (~226MB)
  *.json                 # 빌드 중간 산출물
.github/workflows/
  update.yml             # 매주 자동 갱신 워크플로
```

> GitHub 단일 파일 100MB 한도 대응을 위해 데이터를 분리 저장합니다.

## 주의

- 자동 매칭은 객관 자료(공포번호·공포일자·시행일자) + 텍스트 의미 분석을 조합합니다. 일부 매칭은 법률 본문에 단서가 없는 경우 추정일 수 있습니다.
- 정확한 법령 본문은 [국가법령정보센터](https://www.law.go.kr) 공식 자료를 기준으로 확인하세요.
