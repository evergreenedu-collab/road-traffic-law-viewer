// 2026-06-05: Vercel Cron → GitHub workflow_dispatch(daily_push) 독립 2차 트리거.
// GitHub Actions 예약 cron이 36~122분 늦게 발사되는 문제를 보완. workflow_dispatch는
// 예약과 달리 즉시 실행되므로, 정시(05:30 KST)에 가까운 발송을 보장하는 백업 경로.
// 실제 발송과 중복 방지는 GitHub job 내부의 /api/claim(멱등성)이 담당 — 여기선 트리거만.
//
// GET /api/trigger   (Vercel Cron이 Authorization: Bearer <CRON_SECRET> 자동 첨부)
//   → GH_DISPATCH_TOKEN(fine-grained PAT, Actions:write)으로 daily_push.yml dispatch(ref master).

export const config = { runtime: 'edge' };

const OWNER = 'evergreenedu-collab';
const REPO = 'road-traffic-law-viewer';
const WORKFLOW = 'daily_push.yml';

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

export default async function handler(req) {
  const auth = req.headers.get('authorization') || '';
  if (!process.env.CRON_SECRET || auth !== `Bearer ${process.env.CRON_SECRET}`) {
    return json({ error: 'unauthorized' }, 401);
  }
  const token = process.env.GH_DISPATCH_TOKEN;
  if (!token) return json({ error: 'GH_DISPATCH_TOKEN missing' }, 500);

  const r = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'koroad-cron-trigger',
      },
      body: JSON.stringify({ ref: 'master' }),
    }
  );
  const ok = r.status === 204 || r.status === 200;   // 204 기본, return_run_details 시 200
  const errText = ok ? '' : (await r.text()).slice(0, 300);
  return json({ dispatched: ok, status: r.status, error: errText }, ok ? 200 : 502);
}
