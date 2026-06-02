// 2026-06-02: 다중 사용자 푸시 알림 백엔드 (Vercel Edge Function + Upstash Redis)
// 200명 환경용 보강: recordId(race condition 차단) + deleteToken(사용자별 권한)
//
// 엔드포인트:
//   POST   /api/subscribe   { endpoint, keys: { p256dh, auth } }
//     → record 신규/갱신. 응답에 deleteToken 발급.
//   DELETE /api/subscribe   { endpoint, deleteToken? , recordId? }
//     → 사용자: Origin + deleteToken 일치 시 삭제
//     → 관리자(Bearer ADMIN_TOKEN): recordId 일치 시만 삭제 (race condition 차단)
//   GET    /api/subscribe   (Authorization: Bearer <ADMIN_TOKEN>)
//     → 구독자 리스트(endpoint·keys·recordId만 반환, deleteToken은 제외)

import { Redis } from '@upstash/redis';

export const config = { runtime: 'edge' };

const redis = new Redis({
  url: process.env.KV_REST_API_URL,
  token: process.env.KV_REST_API_TOKEN,
});

const KEY_PREFIX = 'sub:';

const ALLOWED_ORIGINS = new Set([
  'https://evergreenedu-collab.github.io',
  'https://road-traffic-law-viewer.vercel.app',
  'http://localhost:8000',
  'http://127.0.0.1:8000',
]);

function pickOrigin(req) {
  const origin = req.headers.get('origin') || '';
  if (ALLOWED_ORIGINS.has(origin)) return origin;
  if (/^https:\/\/road-traffic-law-viewer-[a-z0-9-]+-evergreenedu-s-projects\.vercel\.app$/.test(origin)) return origin;
  return null;
}

function corsHeaders(req) {
  const allowed = pickOrigin(req);
  const h = {
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Cache-Control': 'no-store',
    'Vary': 'Origin',
  };
  if (allowed) h['Access-Control-Allow-Origin'] = allowed;
  return h;
}

function jsonResponse(req, status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...corsHeaders(req) },
  });
}

function makeKey(endpoint) {
  return KEY_PREFIX + encodeURIComponent(endpoint);
}

function isValidEndpoint(s) {
  if (typeof s !== 'string' || s.length > 2048) return false;
  try {
    const u = new URL(s);
    return u.protocol === 'https:';
  } catch (_) { return false; }
}

function isShortString(s, max) {
  return typeof s === 'string' && s.length > 0 && s.length <= max;
}

function genToken() {
  // Edge runtime은 crypto.randomUUID 지원 (Web Crypto)
  return crypto.randomUUID().replace(/-/g, '');
}

export default async function handler(req) {
  if (req.method === 'OPTIONS') {
    if (!pickOrigin(req)) return new Response(null, { status: 403 });
    return new Response(null, { status: 204, headers: corsHeaders(req) });
  }

  try {
    if (req.method === 'POST') {
      if (!pickOrigin(req)) return jsonResponse(req, 403, { error: 'origin not allowed' });
      const body = await req.json().catch(() => null);
      if (!body || !isValidEndpoint(body.endpoint) ||
          !body.keys || !isShortString(body.keys.p256dh, 256) || !isShortString(body.keys.auth, 64)) {
        return jsonResponse(req, 400, { error: 'invalid subscription' });
      }
      const key = makeKey(body.endpoint);
      // 기존 record가 있으면 recordId·deleteToken 유지 (멱등성) — 페이지 로드 시 자동 재동기화에서 영구 토큰 X
      const existing = await redis.get(key);
      const now = new Date().toISOString();
      const record = {
        endpoint: body.endpoint,
        keys: { p256dh: body.keys.p256dh, auth: body.keys.auth },
        recordId: existing?.recordId || genToken(),
        deleteToken: existing?.deleteToken || genToken(),
        addedAt: existing?.addedAt || now,
        updatedAt: now,
      };
      await redis.set(key, record);
      try { console.log('[push-api] subscribe', new URL(body.endpoint).host); } catch (_) {}
      // 클라이언트에 deleteToken 반환 (재방문 시 동일값 — 안전)
      return jsonResponse(req, 200, { ok: true, deleteToken: record.deleteToken });
    }

    if (req.method === 'DELETE') {
      const auth = req.headers.get('authorization') || '';
      const isAdmin = !!process.env.ADMIN_TOKEN && auth === `Bearer ${process.env.ADMIN_TOKEN}`;
      const body = await req.json().catch(() => null);
      if (!body || !isValidEndpoint(body.endpoint)) {
        return jsonResponse(req, 400, { error: 'endpoint required' });
      }

      const key = makeKey(body.endpoint);

      if (isAdmin) {
        // 관리자(GitHub Actions): recordId 일치 시만 삭제 (race condition 차단)
        // recordId 미제공 시 일치 검증 건너뛰고 무조건 삭제 (사용자 명시적 unsubscribe Admin 호출 케이스)
        if (body.recordId) {
          const existing = await redis.get(key);
          if (existing && existing.recordId !== body.recordId) {
            return jsonResponse(req, 409, { error: 'recordId mismatch — record updated since fetch', skipped: true });
          }
        }
        await redis.del(key);
        try { console.log('[push-api] unsubscribe', new URL(body.endpoint).host, '(admin)'); } catch (_) {}
        return jsonResponse(req, 200, { ok: true, mode: 'admin' });
      }

      // 사용자(브라우저): Origin + deleteToken 검증
      if (!pickOrigin(req)) return jsonResponse(req, 403, { error: 'origin not allowed' });
      if (!isShortString(body.deleteToken, 64)) {
        return jsonResponse(req, 401, { error: 'deleteToken required' });
      }
      const existing = await redis.get(key);
      if (!existing) {
        // 이미 없음 — 무해 처리 (재시도 등)
        return jsonResponse(req, 200, { ok: true, already_gone: true });
      }
      if (existing.deleteToken !== body.deleteToken) {
        return jsonResponse(req, 403, { error: 'deleteToken mismatch' });
      }
      await redis.del(key);
      try { console.log('[push-api] unsubscribe', new URL(body.endpoint).host, '(user)'); } catch (_) {}
      return jsonResponse(req, 200, { ok: true, mode: 'user' });
    }

    if (req.method === 'GET') {
      const auth = req.headers.get('authorization') || '';
      if (!process.env.ADMIN_TOKEN || auth !== `Bearer ${process.env.ADMIN_TOKEN}`) {
        return new Response('Unauthorized', { status: 401, headers: corsHeaders(req) });
      }
      let cursor = '0';
      const keys = [];
      do {
        const [next, batch] = await redis.scan(cursor, { match: `${KEY_PREFIX}*`, count: 200 });
        cursor = next;
        if (Array.isArray(batch) && batch.length) keys.push(...batch);
      } while (cursor !== '0' && cursor !== 0);

      const values = keys.length ? await redis.mget(...keys) : [];
      // 응답에서 deleteToken 제거 — 운영자에게 노출 X
      const safe = values.filter(Boolean).map(s => ({
        endpoint: s.endpoint,
        keys: s.keys,
        recordId: s.recordId,
        addedAt: s.addedAt,
      }));
      console.log('[push-api] list', safe.length, 'subscriptions');
      return jsonResponse(req, 200, { subscriptions: safe });
    }

    return jsonResponse(req, 405, { error: 'method not allowed' });
  } catch (e) {
    console.error('[push-api] error:', e?.message || e);
    return jsonResponse(req, 500, { error: String(e?.message || e) });
  }
}
