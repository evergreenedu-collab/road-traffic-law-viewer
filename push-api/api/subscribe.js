// 2026-06-02: 다중 사용자 푸시 알림 백엔드 (Vercel Edge Function + Upstash Redis)
// Codex 검증 반영: Origin 화이트리스트 + Bearer 인증 + Cache-Control + 입력 검증 강화
//
// 엔드포인트:
//   POST   /api/subscribe   { endpoint, keys: { p256dh, auth } }    (Origin 화이트리스트만)
//   DELETE /api/subscribe   { endpoint }                            (Origin 또는 Admin Bearer)
//   GET    /api/subscribe   (Authorization: Bearer <ADMIN_TOKEN>)   (GitHub Actions 전용)

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
      const record = {
        endpoint: body.endpoint,
        keys: { p256dh: body.keys.p256dh, auth: body.keys.auth },
        addedAt: new Date().toISOString(),
      };
      await redis.set(makeKey(body.endpoint), record);
      try { console.log('[push-api] subscribe', new URL(body.endpoint).host); } catch (_) {}
      return jsonResponse(req, 200, { ok: true });
    }

    if (req.method === 'DELETE') {
      const auth = req.headers.get('authorization') || '';
      const isAdmin = !!process.env.ADMIN_TOKEN && auth === `Bearer ${process.env.ADMIN_TOKEN}`;
      if (!isAdmin && !pickOrigin(req)) return jsonResponse(req, 403, { error: 'origin not allowed' });
      const body = await req.json().catch(() => null);
      if (!body || !isValidEndpoint(body.endpoint)) {
        return jsonResponse(req, 400, { error: 'endpoint required' });
      }
      await redis.del(makeKey(body.endpoint));
      try { console.log('[push-api] unsubscribe', new URL(body.endpoint).host, isAdmin ? '(admin)' : ''); } catch (_) {}
      return jsonResponse(req, 200, { ok: true });
    }

    if (req.method === 'GET') {
      const auth = req.headers.get('authorization') || '';
      if (!process.env.ADMIN_TOKEN || auth !== `Bearer ${process.env.ADMIN_TOKEN}`) {
        return new Response('Unauthorized', { status: 401, headers: corsHeaders(req) });
      }
      let cursor = '0';
      const keys = [];
      do {
        const [next, batch] = await redis.scan(cursor, { match: `${KEY_PREFIX}*`, count: 100 });
        cursor = next;
        if (Array.isArray(batch) && batch.length) keys.push(...batch);
      } while (cursor !== '0' && cursor !== 0);

      const values = keys.length ? await redis.mget(...keys) : [];
      const subs = values.filter(Boolean);
      console.log('[push-api] list', subs.length, 'subscriptions');
      return jsonResponse(req, 200, { subscriptions: subs });
    }

    return jsonResponse(req, 405, { error: 'method not allowed' });
  } catch (e) {
    console.error('[push-api] error:', e?.message || e);
    return jsonResponse(req, 500, { error: String(e?.message || e) });
  }
}
