# tutor — 일일 법령 학습 튜터

도로교통법-한눈에 사이트에 통합된 일일 학습 채널.
국가법령정보센터 API 원본을 근거로 매일 "한 줄 법령 + 30초 해설"을 자동 생성하여 웹푸시로 발송한다.

## 현재 단계
M0 — 폴더 골격 초기화 완료. 후속 마일스톤에서 실제 파일이 채워진다.

## 예정 구조
- `index.html` — 일일 학습 페이지 (M3)
- `sw.js` — 서비스 워커, 웹푸시 수신 (M6)
- `build_tutor_content.py` — 매일 콘텐츠 자동 생성 (M1·M2)
- `data/daily_YYYY-MM-DD.json` — 매일 생성되는 콘텐츠
- `cloudflare-worker/` — 푸시 발송 백엔드 (M5)

## 기획 문서
`C:\Users\user\.claude\plans\async-riding-dream.md`
