# push-api — 다중 사용자 푸시 알림 백엔드

도로교통법-한눈에 + 출근길 법령튜터의 여러 구독자 endpoint를 모으는 Vercel Edge Function.

## 엔드포인트

- `POST /api/subscribe` — 클라이언트가 구독 시 endpoint 등록
- `DELETE /api/subscribe` — 구독 취소 시 endpoint 제거
- `GET /api/subscribe?token=...` — GitHub Actions가 매일 06:30에 전체 구독자 fetch

## Vercel 설정

1. Vercel Dashboard → 이 프로젝트 → **Settings → General → Root Directory** = `push-api`
2. **Storage → Create Database → KV** → 프로젝트에 Connect
3. **Settings → Environment Variables** → `ADMIN_TOKEN` 추가 (GitHub Actions 인증용 비밀 토큰)

## 보안

`GET /api/subscribe`는 `ADMIN_TOKEN` 일치 시에만 응답. `POST/DELETE`는 사용자 공개 (구독자 자신만 자기 endpoint 관리).
