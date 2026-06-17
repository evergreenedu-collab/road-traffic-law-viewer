// 2026-06-05: 푸시 발송 멱등성 — 하루 1회 보장.
// Vercel Cron→workflow_dispatch + GitHub schedule cron 이중 트리거가 같은 날 둘 다 발송하는 중복 방지.
// 실제 발송자(GitHub Actions job)가 발송 직전 lock을 획득하고, 성공 후 sent를 기록한다.
//
// POST /api/claim    (인증: Authorization: Bearer <ADMIN_TOKEN> 또는 ?token=<ADMIN_TOKEN>)
//   body { date: 'YYYY-MM-DD'(KST 업무일), phase: 'acquire' | 'done' }
//   - acquire: push:sent:<date> 있으면 {send:false,'already_sent'}.
//              없으면 push:lock:<date> SET NX EX 2h → 획득 시 {send:true}, 이미 lock이면 {send:false,'locked'}.
//   - done:    push:sent:<date> SET EX 36h + lock 해제 → {ok:true}.
//
// ⚠️ 호출자(GitHub) fail-safe: 응답이 명시적으로 {send:false}일 때만 발송 스킵.
//    그 외(오류·5xx·네트워크 실패)는 발송 진행 — "오늘은 무조건 발송"(누락 < 중복) 정책.

import { Redis } from '@upstash/redis';

export const config = { runtime: 'edge' };

const redis = new Redis({
  url: process.env.KV_REST_API_URL,
  token: process.env.KV_REST_API_TOKEN,
});

const LOCK_TTL = 7200;     // 2h — 발송 진행 중 잠금 (실패 시 자동 해제 후 재시도 가능)
const SENT_TTL = 129600;   // 36h — 그날 발송 완료 표식

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function getToken(req, url) {
  const m = (req.headers.get('authorization') || '').match(/^Bearer\s+(.+)$/i);
  return (m && m[1]) || url.searchParams.get('token') || '';
}

export default async function handler(req) {
  if (req.method !== 'POST') return json({ error: 'method not allowed' }, 405);

  const url = new URL(req.url);
  if (!process.env.ADMIN_TOKEN || getToken(req, url) !== process.env.ADMIN_TOKEN) {
    return json({ error: 'unauthorized' }, 401);
  }

  let body = {};
  try { body = await req.json(); } catch { /* 아래 date 검증에서 거름 */ }
  const date = String(body?.date || '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return json({ error: 'date(YYYY-MM-DD, KST) required' }, 400);
  }
  const phase = body?.phase === 'done' ? 'done' : 'acquire';
  const sentKey = `push:sent:${date}`;
  const lockKey = `push:lock:${date}`;

  try {
    if (phase === 'done') {
      await redis.set(sentKey, new Date().toISOString(), { ex: SENT_TTL });
      await redis.del(lockKey);
      return json({ ok: true, marked: 'sent', date });
    }
    // acquire
    if (await redis.get(sentKey)) {
      return json({ send: false, reason: 'already_sent', date });
    }
    const got = await redis.set(lockKey, new Date().toISOString(), { nx: true, ex: LOCK_TTL });
    if (!got) return json({ send: false, reason: 'locked', date });
    // 레이스 보강 — lock 획득 직후 sent 재확인 (get(sent)~set(lock) 사이 다른 실행이 done 했을 수 있음)
    if (await redis.get(sentKey)) {
      await redis.del(lockKey);
      return json({ send: false, reason: 'already_sent', date });
    }
    return json({ send: true, date });
  } catch (e) {
    // Redis 일시 장애 등 — 호출자는 명시적 send:false가 아니므로 발송 진행(fail-open)
    return json({ error: String(e?.message || e) }, 500);
  }
}
