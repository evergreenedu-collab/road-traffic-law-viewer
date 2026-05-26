// 출근길 법령튜터 PWA Service Worker
// PR-H1: 기본 등록 + 푸시·알림 클릭 스켈레톤
// PR-H4에서 알림 표시·진입 흐름 정교화 예정

const SW_VERSION = 'pwa-h1-2026-05-26';

self.addEventListener('install', (event) => {
  // 정적 자료는 페이지 자체 캐시버스팅(?v=빌드시각) 사용 — SW는 즉시 활성화
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // 이전 SW가 있다면 즉시 교체
  event.waitUntil(self.clients.claim());
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
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || './tutor/';
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
