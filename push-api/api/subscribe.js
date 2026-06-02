// 2026-06-02: 다중 사용자 푸시 알림 백엔드 (Vercel Edge Function + Upstash Redis)
// 엔드포인트:
//   POST   /api/subscribe   { endpoint, keys: { p256dh, auth } }
//     → Redis에 endpoint를 키로 저장. 중복 방지 (같은 endpoint = 같은 key).
//   DELETE /api/subscribe   { endpoint }
//     → Redis에서 해당 endpoint 제거.
//   GET    /api/subscribe?token=<ADMIN_TOKEN>
//     → GitHub Actions가 모든 구독자 리스트를 가져갈 때 사용.
//        토큰 검증 후 [{ endpoint, keys, addedAt }, ...] 반환.
//
// @upstash/redis는 Edge Function에서 fetch 기반으로 동작 (Node 모듈 X).
// Upstash for Redis Integration이 KV_REST_API_URL · KV_REST_API_TOKEN 환경변수 자동 주입.

import { Redis } from '@upstash/redis';

export const config = { runtime: 'edge' };

const redis = new Redis({
  url: process.env.KV_REST_API_URL,
  token: process.env.KV_REST_API_TOKEN,
});

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
      // Upstash Redis는 object를 직접 받으면 내부에서 JSON.stringify 처리
      await redis.set(makeKey(body.endpoint), record);
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
      await redis.del(makeKey(body.endpoint));
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
      // SCAN으로 sub:* 키 전수 수집 (cursor 0 → 0)
      let cursor = '0';
      const keys = [];
      do {
        const [next, batch] = await redis.scan(cursor, { match: `${KEY_PREFIX}*`, count: 100 });
        cursor = next;
        if (Array.isArray(batch) && batch.length) keys.push(...batch);
      } while (cursor !== '0' && cursor !== 0);

      const values = keys.length ? await redis.mget(...keys) : [];
      // Upstash Redis는 mget에서 저장 시 사용한 형식 그대로 반환 (object → object)
      return new Response(JSON.stringify({ subscriptions: values.filter(Boolean) }), {
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
