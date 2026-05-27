// PR-H9: viewer JS 스모크 테스트 — syntax 검증
// 사용: node tests/smoke_viewer.js viewer.html viewer_tlspc.html ...
//
// 회귀 방지 — 오늘 brace `}` 한 줄 잘못 박혀 viewer 전체 깨졌던 사고 재발 차단.
// CI에서 deploy_pages 전 자동 실행 → syntax 에러 시 배포 차단.
//
// jsdom 같은 풀 실행 환경은 너무 strict (TDZ 등 false positive). 단순 syntax 검증이
// brace mismatch·괄호 누락·잘못된 return 등 실제 사용자 도달 가능한 에러를 잘 잡음.

const fs = require('fs');

// 외부 src 로드 script는 inline content 검사 X (속성 안 < 같은 false positive 회피)
// src 속성이 있는 태그만 식별. 정밀 regex로 attr 안 따옴표 처리.
const SCRIPT_TAG_RE = /<script\b([^>]*)>([\s\S]*?)<\/script>/g;

function checkFile(htmlPath) {
  if (!fs.existsSync(htmlPath)) {
    return { ok: false, reason: 'NOT_FOUND' };
  }
  const html = fs.readFileSync(htmlPath, 'utf-8');
  const errors = [];
  let blockIdx = 0;

  let m;
  while ((m = SCRIPT_TAG_RE.exec(html)) !== null) {
    blockIdx++;
    const attrs = m[1] || '';
    const code = m[2] || '';
    // src="..." 있는 외부 script는 content 검사 skip (속성 안 < 가 false positive)
    if (/\bsrc\s*=/.test(attrs)) continue;
    if (!code.trim()) continue;

    try {
      new Function(code);
    } catch (e) {
      const startLine = html.substring(0, m.index).split('\n').length;
      errors.push({ block: blockIdx, line: startLine, msg: e.message });
    }
  }

  // 추가 검사: 'Illegal return' 같은 패턴은 new Function이 잡지만, 직접 패턴 검사로 보강
  // (오늘 발생한 brace mismatch도 new Function이 잡음 — 이미 커버됨)

  if (errors.length === 0) return { ok: true, blocks: blockIdx };
  return { ok: false, errors, blocks: blockIdx };
}

function main() {
  const files = process.argv.slice(2);
  if (files.length === 0) {
    console.error('Usage: node smoke_viewer.js <html files...>');
    process.exit(2);
  }

  let failed = 0;
  for (const f of files) {
    process.stdout.write(`🧪 ${f} ... `);
    const r = checkFile(f);
    if (r.ok) {
      console.log(`✅ (${r.blocks} script 블록)`);
    } else {
      failed++;
      console.log('❌');
      if (r.reason) console.log('  -', r.reason);
      if (r.errors) {
        for (const e of r.errors) {
          console.log(`  ⚠️ 블록 ${e.block} (라인 ${e.line} 부근): ${e.msg}`);
        }
      }
    }
  }

  if (failed > 0) {
    console.error(`\n❌ ${failed}/${files.length} 실패 — Pages 배포 차단`);
    process.exit(1);
  }
  console.log(`\n✅ ${files.length}/${files.length} syntax 통과`);
}

main();
