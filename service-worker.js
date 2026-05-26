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
  let payload = { title: '출근길 법령튜터', body: '오늘의 카드가 도착했어요.', url: './tutor/' };
  if (event.data) {
    try {
      payload = Object.assign(payload, event.data.json());
    } catch (e) {
      // payload가 JSON이 아니면 텍스트로
      payload.body = event.data.text() || payload.body;
    }
  }
  const opts = {
    body: payload.body,
    icon: './icons/icon-192.svg',
    badge: './icons/icon-192.svg',
    data: { url: payload.url || './tutor/' },
    tag: 'daily-tutor',
    renotify: true,
  };
  event.waitUntil(self.registration.showNotification(payload.title, opts));
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
