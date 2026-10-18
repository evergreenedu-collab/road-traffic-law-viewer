// 2026-10-18: 공개 방문 카운터 — 외국인 학과시험 AI튜터(quiz) 등 GitHub Pages 사이트용.
// 집계 시작일부터의 실측값만 제공한다 (임의 시작값·보정 없음).
//
// POST /api/hit?site=quiz  → INCR 후 {count}
// GET  /api/hit?site=quiz  → 조회만 {count}
// site 화이트리스트 외는 400. CORS는 운영 Pages 오리진만 허용.

import { Redis } from '@upstash/redis';

export const config = { runtime: 'edge' };

const redis = new Redis({
  url: process.env.KV_REST_API_URL,
  token: process.env.KV_REST_API_TOKEN,
});

const SITES = new Set(['quiz', 'rtl']);
const ALLOW_ORIGIN = 'https://evergreenedu-collab.github.io';

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': ALLOW_ORIGIN,
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Cache-Control': 'no-store',
    },
  });
}

export default async function handler(req) {
  if (req.method === 'OPTIONS') return json({ ok: true });
  if (req.method !== 'GET' && req.method !== 'POST') {
    return json({ error: 'method not allowed' }, 405);
  }
  const url = new URL(req.url);
  const site = String(url.searchParams.get('site') || '').trim();
  if (!SITES.has(site)) return json({ error: 'unknown site' }, 400);

  const key = `visits:${site}`;
  try {
    const count = req.method === 'POST'
      ? await redis.incr(key)
      : Number(await redis.get(key)) || 0;
    return json({ count });
  } catch (e) {
    return json({ error: 'redis error' }, 500);
  }
}
