# viewer.html 다중 법령 UI 설계서

## 목적
도로교통법 단일 viewer를 **6개 법령(+α) 통합 viewer**로 확장. 사용자 결정 A1(드롭다운 통합) 반영.

## 현재 구조 요약 (도교법 단일)
- 상단: 조문 셀렉트 (`<select id="sel">`)
- 본문: 3단 비교 그리드 — 법률 / 시행령 / 시행규칙
- 우측 패널: 연혁 / 부칙별도시행일 / 첨부표 / 개정이유
- 데이터: `web_data/data_core.js` 단일 파일에 `mapData`, `artData`, `tableData`, `cascadeData`, `diffData` 5개 전역 객체 로드

## 다중 법령 변경 사항

### 1. 상단 UI 추가
```
┌──────────────────────────────────────────────────────────────┐
│ 법령: [도로교통법 ▼]  조문: [제44조 — 술에 취한 상태에서의 운전금지 ▼]│
└──────────────────────────────────────────────────────────────┘
```

드롭다운 옵션 (sources_config.json의 law_code 기반):
- 도로교통법 (3단)
- 도로교통법 시행령 (도교법 그룹의 일부, 사용자 선호 시 그룹 옵션)
- 교통사고처리 특례법 (단일)
- 특정범죄 가중처벌법 (단일)
- 자동차관리법 (3단)
- 여객자동차 운수사업법 (3단)
- 화물자동차 운수사업법 (3단)
- 형사소송법 (단일)

기본 선택값: **"도로교통법"** (기존 사용 경험 보존)

### 2. 모드 자동 전환

`has_subordinate=true` 법령 (도교법·자관법·운수사업법):
- 기존 3단 그리드 유지

`has_subordinate=false` 법령 (교특법·특가법·형소법):
```
┌────────────────────────────────────────┐
│ 법률 (단일 모드)                       │
│                                        │
│ ┌────────────────────────────────────┐ │
│ │ 조문 본문                          │ │
│ │                                    │ │
│ └────────────────────────────────────┘ │
│                                        │
│ [연혁] [부칙별도시행일] [개정이유]     │
└────────────────────────────────────────┘
```

→ CSS `grid-template-columns`를 동적으로 `repeat(3, 1fr)` ↔ `1fr`로 전환.

### 3. 데이터 로드 (Lazy Load)

**현재**: `<script src="web_data/data_core.js">` 한 줄에 모든 데이터.

**변경**: 법령 선택 시 fetch:
```javascript
async function loadLaw(lawCode) {
  if (LOADED[lawCode]) return LOADED[lawCode];
  const resp = await fetch(`web_data/data_core_${lawCode}.js`);
  const text = await resp.text();
  // eval 또는 안전한 모듈 로더
  // ...
  LOADED[lawCode] = parsed;
  return parsed;
}
```

법령별 분리:
- `data_core_road.js` (도교법 + 시행령 + 시행규칙)
- `data_core_tlspc.js` (교특법, 단일)
- `data_core_tkga.js` (특가법, 단일)
- `data_core_car_mgmt.js` (자관법 그룹)
- `data_core_passenger_transport.js`
- `data_core_cargo_transport.js`
- `data_core_crim_proc.js` (형소법, 단일)

→ 초기 로드 시 도교법만 로드, 나머지는 사용자가 선택할 때.

### 4. 조문 식별자 변경

현재: `?jo=44` → 도교법 제44조 (단일 법령 가정)
변경: `?law=road&jo=44` → 명시적 법령코드 + 조문

URL 호환성: `?jo=44` 단독은 `law=road` 기본값으로 처리 (기존 북마크 보존).

### 5. 캐시 함정 회피

기존 메모리에 적힌 캐시 함정: `web_data/*.js`가 캐시버스팅 쿼리 없이 로드되어 시크릿 창 필수.

**개선안 (선택)**: data_core 파일에 빌드 타임스탬프 쿼리 추가:
```html
<script src="web_data/data_core_road.js?v=20260521"></script>
```
또는 fetch 사용 시 `cache: 'no-cache'` 옵션. lazy load 도입 시점에 자연스럽게 해결.

## 코드 변경 포인트 (Stage 3 작업)

| 파일 | 변경 내용 |
|---|---|
| `viewer.html` | 드롭다운 추가, 모드 전환 함수 신설, lazy load 구현 |
| `generate_viewer.py` | data_core 분리 출력 (법령 코드별 .js 파일) |
| `web_data/data_core.js` | 삭제 또는 도교법 전용 alias로 변경 (호환성) |

신규 함수 추가 위치 (viewer.html `<script>` 내):
- `loadLaw(lawCode)` — fetch + 캐싱
- `switchLaw(lawCode)` — UI 전환 + render() 호출
- `getLayoutMode(lawCode)` — has_subordinate 조회 → 'tri' / 'single'

기본 변수 의존성 — 현재 `mapData`, `artData` 전역 → **객체로 묶어 `STATE.current = {map, art, table, cascade, diff}`** 형태로 리팩터링 권장.

## 위험·함정

1. **전역 변수 의존성** — 현재 `mapData`, `artData`가 모듈 스코프 전역. 다중 법령은 객체 묶음으로 갈아엎어야 함. 미들 코드 30~50줄 영향.
2. **3단 → 단일 전환 CSS** — `grid-template-columns` 동적 변경 시 우측 패널(연혁 등) 위치도 같이 조정. 모바일 반응형 검증 필요.
3. **법령 그룹 vs 단일 법령 표현** — "도로교통법" 선택 시 3단 그리드 자동 표시 vs "도로교통법 시행령" 단독 선택 옵션 — UX 결정 필요. **권장**: 그룹 단위로만 노출 (사용자 단순화). 시행령·시행규칙 단독은 그리드 내에서만.
4. **URL 호환성** — 기존 북마크(`?jo=N`)는 `law=road` 기본값으로 매핑. 단 일부 사용자가 직접 URL을 작성하던 경우 안내 메시지 필요.
5. **검색·필터 UI** — 현재 조문 셀렉트는 단일 법령 조문만. 법령 전환 시 셀렉트도 재구성 필요.
6. **연혁 패널 호환** — 연혁 데이터(`diffData`)가 법령별로 구조 동일한지 검증. text_diff.json 파싱 로직 재사용 가능 여부.
7. **별표 패널 (도교법 시행령·규칙 전용)** — has_subordinate=false 법령에선 별표 패널 자동 숨김. UI 분기 필요.

## 작업 순서 (Stage 3 세분화)

1. **3-1**: `data_core_road.js` 분리 출력만 — 기존 viewer.html은 그대로 사용. **회귀 없음 확인**.
2. **3-2**: viewer.html에 lazy load 도입 — `data_core_road.js`만 동적 로드로 변환. **회귀 없음 확인**.
3. **3-3**: 드롭다운 UI + `STATE.current` 객체 리팩터링. 도교법만 선택 가능 상태. **회귀 없음 확인**.
4. **3-4**: 두 번째 법령(교특법) 추가 — 단일 모드 자동 전환 동작 검증.
5. **3-5**: 나머지 4개 법령 순차 추가.
6. **3-6**: 별표·연혁 패널 단일 모드 호환 정리.

각 단계에서 시크릿 창으로 회귀 확인.
