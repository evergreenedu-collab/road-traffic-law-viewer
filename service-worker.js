// 출근길 법령튜터 PWA Service Worker
// PR-H1: 기본 등록 + 푸시·알림 클릭 스켈레톤
// PR-H4에서 알림 표시·진입 흐름 정교화 예정
// PR-H10-β: viewer web_data/*.js cache-first 전략 — 두 번째 진입부터 네트워크 0

const SW_VERSION = 'pwa-h10-2026-05-28';
const DATA_CACHE = 'viewer-data-v1';   // ?v= 캐시버스팅이 URL에 포함되므로 새 빌드는 자동 무효화 (새 URL → cache miss → 새 fetch)

self.addEventListener('install', (event) => {
  // 정적 자료는 페이지 자체 캐시버스팅(?v=빌드시각) 사용 — SW는 즉시 활성화
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // 이전 SW가 있다면 즉시 교체 + 옛 viewer-data-* 캐시 정리
  event.waitUntil((async () => {
    try {
      const names = await caches.keys();
      await Promise.all(names
        .filter(n => n.startsWith('viewer-data-') && n !== DATA_CACHE)
        .map(n => caches.delete(n))
      );
    } catch (e) {
      console.warn('[sw] 옛 캐시 정리 실패:', e);
    }
    await self.clients.claim();
  })());
});

// PR-H10-β: viewer web_data/*.js cache-first 전략
// 캐시 키 = URL (?v=빌드TS 포함) → 새 빌드 = 새 URL = 자동 무효화
// 디스크 정리는 1차에서 보류 (Codex 권장 — 같은 v1 캐시 안 옛 ?v= 항목은 자연스레 hit 없이 잠자도록)
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  let url;
  try { url = new URL(event.request.url); } catch (e) { return; }
  if (url.origin !== self.location.origin) return;
  // /web_data/data_*.js 또는 /road-traffic-law-viewer/web_data/data_*.js (Pages 배포 경로)
  if (!/\/web_data\/data_.+\.js$/.test(url.pathname)) return;

  event.respondWith((async () => {
    try {
      const cache = await caches.open(DATA_CACHE);
      const hit = await cache.match(event.request);
      if (hit) return hit;
      const res = await fetch(event.request);
      if (res && res.ok) {
        // quota 초과/cache.put 실패는 silent — 응답은 정상 반환
        cache.put(event.request, res.clone()).catch(() => {});
      }
      return res;
    } catch (e) {
      // 캐시 API 자체 실패 (시크릿 모드 등) — 네트워크 폴백
      return fetch(event.request);
    }
  })());
});

// 푸시 수신 (PR-H3 GitHub Actions에서 web-push로 발송)
// 발송 페이로드 예시:
//   { "title": "🚗 출근길 법령튜터 — 오늘의 5장",
//     "body":  "🟦월 음주운전 · 🟦화 음주판례 · 🟦수 무면허 · 🟩목 양벌 · 🟪금 화물종사자격",
//     "url":   "./tutor/?date=2026-05-26" }
self.addEventListener('push', (event) => {
  // PR-H3-β 디버그 — push 이벤트 도달 자체 진단 (chrome://inspect SW 콘솔에서 확인 가능)
  console.log('[push]', new Date().toISOString(), event.data && event.data.text());
  let payload = { title: '출근길 법령튜터', body: '오늘의 카드가 도착했어요.', url: '/road-traffic-law-viewer/tutor/' };
  if (event.data) {
    try {
      payload = Object.assign(payload, event.data.json());
    } catch (e) {
      payload.body = event.data.text() || payload.body;
    }
  }
  // Codex 권장 — icon/badge 옵션 제거 (SVG가 Android Chrome notification에서 표시 안 되는 경우 회피)
  // 알림 표시 자체가 안 되는 1순위 원인 검증용. 도착 확인 후 PNG로 보강 예정.
  const opts = {
    body: payload.body,
    data: { url: payload.url || '/road-traffic-law-viewer/tutor/' },
    tag: 'daily-tutor',
    renotify: true,
  };
  event.waitUntil(
    self.registration.showNotification(payload.title, opts)
      .then(() => console.log('[push] showNotification OK'))
      .catch(e => console.error('[push] showNotification 실패:', e))
  );
});

// 알림 클릭 — 튜터 페이지로 진입 (이미 열려 있으면 focus)
// PR-H8-audit (Codex#8): URL을 self.registration.scope 기준으로 정규화 — 배포 경로 변경에 안전
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const scope = self.registration.scope;   // 예: https://evergreenedu-collab.github.io/road-traffic-law-viewer/
  const rawUrl = (event.notification.data && event.notification.data.url) || 'tutor/';
  // 상대경로면 scope 기준 절대화, 절대경로면 그대로
  let targetUrl;
  try {
    targetUrl = new URL(rawUrl, scope).href;
  } catch (e) {
    targetUrl = scope + 'tutor/';   // 최후 폴백
  }
  event.waitUntil((async () => {
    const all = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const c of all) {
      if (c.url.includes('/tutor/') && 'focus' in c) {
        await c.focus();
        if (c.navigate) await c.navigate(targetUrl);
        return;
      }
    }
    if (self.clients.openWindow) {
      await self.clients.openWindow(targetUrl);
    }
  })());
});
