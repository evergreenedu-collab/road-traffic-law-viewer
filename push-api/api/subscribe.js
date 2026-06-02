// 2026-06-02: 다중 사용자 푸시 알림 백엔드 (Vercel Edge Function + Vercel KV)
// 엔드포인트:
//   POST   /api/subscribe   { endpoint, keys: { p256dh, auth } }
//     → KV에 endpoint를 키로 저장. 중복 방지 (같은 endpoint = 같은 key).
//   DELETE /api/subscribe   { endpoint }
//     → KV에서 해당 endpoint 제거.
//   GET    /api/subscribe?token=<ADMIN_TOKEN>
//     → GitHub Actions가 모든 구독자 리스트를 가져갈 때 사용.
//        토큰 검증 후 [{ endpoint, keys, addedAt }, ...] 반환.

import { kv } from '@vercel/kv';

export const config = { runtime: 'edge' };

const KEY_PREFIX = 'sub:';

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

function makeKey(endpoint) {
  return KEY_PREFIX + encodeURIComponent(endpoint);
}

export default async function handler(req) {
  if (req.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders() });
  }

  try {
    if (req.method === 'POST') {
      const body = await req.json();
      if (!body?.endpoint || !body?.keys?.p256dh || !body?.keys?.auth) {
        return new Response(JSON.stringify({ error: 'invalid subscription' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json', ...corsHeaders() },
        });
      }
      const record = {
        endpoint: body.endpoint,
        keys: { p256dh: body.keys.p256dh, auth: body.keys.auth },
        addedAt: new Date().toISOString(),
      };
      await kv.set(makeKey(body.endpoint), record);
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ...corsHeaders() },
      });
    }

    if (req.method === 'DELETE') {
      const body = await req.json();
      if (!body?.endpoint) {
        return new Response(JSON.stringify({ error: 'endpoint required' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json', ...corsHeaders() },
        });
      }
      await kv.del(makeKey(body.endpoint));
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ...corsHeaders() },
      });
    }

    if (req.method === 'GET') {
      const url = new URL(req.url);
      const token = url.searchParams.get('token');
      if (!process.env.ADMIN_TOKEN || token !== process.env.ADMIN_TOKEN) {
        return new Response('Unauthorized', { status: 401, headers: corsHeaders() });
      }
      // KV에 저장된 모든 구독자 키 조회 → 값 fetch
      const keys = [];
      for await (const k of kv.scanIterator({ match: `${KEY_PREFIX}*` })) {
        keys.push(k);
      }
      const subs = keys.length ? await kv.mget(...keys) : [];
      return new Response(JSON.stringify({ subscriptions: subs.filter(Boolean) }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', ...corsHeaders() },
      });
    }

    return new Response(JSON.stringify({ error: 'method not allowed' }), {
      status: 405,
      headers: { 'Content-Type': 'application/json', ...corsHeaders() },
    });
  } catch (e) {
    return new Response(JSON.stringify({ error: String(e?.message || e) }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', ...corsHeaders() },
    });
  }
}
