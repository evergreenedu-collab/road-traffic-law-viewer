"""52건 사고상황도 HTML 자동 생성. /diagrams/ 폴더에 저장.

매핑표는 c:/Users/user/projects/판례조회-AI도구/GPT_Instructions_본문만.md의 §6 끝 부분에서 파싱.
템플릿 A의 wrap 구조 공통 적용 + 템플릿 A~F별 SVG.
"""
import re
import pathlib

SRC = pathlib.Path('../판례조회-AI도구/GPT_Instructions_본문만.md')
OUT = pathlib.Path('diagrams')

# 매핑 데이터 파싱
text = SRC.read_text(encoding='utf-8')
m = re.search(r'## 52건 매핑표.*?\n(.*)', text, re.DOTALL)
rows = []
for line in m.group(1).splitlines():
    line = line.strip()
    if not line.startswith('|') or '---' in line or '사건번호' in line:
        continue
    cells = [c.strip() for c in line.strip('|').split('|')]
    if len(cells) >= 4:
        rows.append({'case_no': cells[0], 'template': cells[1], 'desc': cells[2], 'verdict': cells[3]})

NOT_GUILTY = {'무과실', '보호의무아님', '보호의무없음', '신뢰원칙', '침범해당않음', '침범≠원인', '파기(무과실)'}

def verdict_class(v):
    return 'v-not-guilty' if v in NOT_GUILTY else 'v-guilty'

COMMON_STYLE = """<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Noto Sans KR',Arial,sans-serif;background:#f5f5f5;padding:20px}
.wrap{max-width:760px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08)}
.title-bar{background:#1E2761;padding:14px 20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}
.title-bar h1{color:#fff;font-size:17px;font-weight:700}
.title-bar span{color:#bbc6ff;font-size:12px}
.summary{padding:14px 20px;background:#f0f1f5;font-size:13px;line-height:1.7;color:#333;border-bottom:1px solid #ddd}
.summary b{color:#1E2761}
.diagram{padding:20px;display:flex;justify-content:center;background:#fff}
.verdict{padding:16px 20px;text-align:center}
.verdict.v-not-guilty{background:#1E2761}
.verdict.v-not-guilty h2{color:#FFD200;font-size:15px;font-weight:700;margin-bottom:6px}
.verdict.v-not-guilty p{color:#d8defa;font-size:12px;line-height:1.6}
.verdict.v-guilty{background:#7c1d1d}
.verdict.v-guilty h2{color:#ffd6d6;font-size:15px;font-weight:700;margin-bottom:6px}
.verdict.v-guilty p{color:#fbe5e5;font-size:12px;line-height:1.6}
.footer{padding:14px 20px;text-align:center;font-size:11px;color:#888;border-top:1px solid #eee;background:#fafafa}
.footer a{color:#7c3aed;text-decoration:none}
.footer a:hover{text-decoration:underline}
</style>"""


def svg_A(case_no):
    return f'''<svg viewBox="0 0 660 440" width="100%" style="max-width:660px">
<defs><marker id="arr-{case_no}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round"/></marker></defs>
<rect x="0" y="170" width="660" height="110" fill="#666"/>
<rect x="275" y="0" width="110" height="440" fill="#666"/>
<rect x="275" y="170" width="110" height="110" fill="#555"/>
<line x1="0" y1="225" x2="275" y2="225" stroke="#FFD200" stroke-width="2"/>
<line x1="385" y1="225" x2="660" y2="225" stroke="#FFD200" stroke-width="2"/>
<line x1="330" y1="0" x2="330" y2="170" stroke="#FFD200" stroke-width="2"/>
<line x1="330" y1="280" x2="330" y2="440" stroke="#FFD200" stroke-width="2"/>
<text x="330" y="160" text-anchor="middle" fill="#333" font-size="13" font-weight="700">신호등 교차로</text>
<rect x="245" y="290" width="20" height="50" rx="4" fill="#333"/><circle cx="255" cy="303" r="5" fill="#555"/><circle cx="255" cy="316" r="5" fill="#555"/><circle cx="255" cy="329" r="5" fill="#33cc66"/><text x="255" y="355" text-anchor="middle" fill="#33cc66" font-size="10" font-weight="700">녹색</text>
<rect x="395" y="105" width="20" height="50" rx="4" fill="#333"/><circle cx="405" cy="118" r="5" fill="#ee3333"/><circle cx="405" cy="131" r="5" fill="#555"/><circle cx="405" cy="144" r="5" fill="#555"/><text x="405" y="100" text-anchor="middle" fill="#ee3333" font-size="10" font-weight="700">적색</text>
<rect x="80" y="237" width="60" height="26" rx="6" fill="#DC3C37"/><text x="110" y="254" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">피고인</text>
<line x1="140" y1="250" x2="270" y2="250" stroke="#DC3C37" stroke-width="2" stroke-dasharray="6 4" marker-end="url(#arr-{case_no})"/>
<rect x="510" y="197" width="60" height="26" rx="6" fill="#3282B8"/><text x="540" y="214" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">상대방</text>
<path d="M510 210 Q430 210 370 230 Q340 240 330 260" fill="none" stroke="#3282B8" stroke-width="2" stroke-dasharray="6 4"/>
<polygon points="330,240 336,228 344,236 350,224 342,238 352,242 340,244 348,254 338,246 332,256 334,244 322,246 332,242 324,234" fill="#FFD200"/>
<text x="330" y="218" text-anchor="middle" fill="#ee3333" font-size="11" font-weight="700">충돌!</text>
</svg>'''


def svg_B(case_no):
    return f'''<svg viewBox="0 0 660 300" width="100%" style="max-width:660px">
<defs><marker id="arr-{case_no}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round"/></marker></defs>
<rect x="0" y="90" width="660" height="120" fill="#666"/>
<rect x="0" y="90" width="660" height="3" fill="#888"/><rect x="0" y="207" width="660" height="3" fill="#888"/>
<line x1="0" y1="148" x2="660" y2="148" stroke="#FFD200" stroke-width="2"/>
<line x1="0" y1="152" x2="660" y2="152" stroke="#FFD200" stroke-width="2"/>
<text x="50" y="180" fill="#999" font-size="16">&#8594;</text><text x="600" y="135" fill="#999" font-size="16">&#8592;</text>
<rect x="120" y="162" width="60" height="26" rx="6" fill="#DC3C37"/><text x="150" y="179" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">피고인</text>
<line x1="180" y1="175" x2="280" y2="175" stroke="#DC3C37" stroke-width="2" stroke-dasharray="6 4" marker-end="url(#arr-{case_no})"/>
<rect x="480" y="115" width="60" height="26" rx="6" fill="#3282B8"/><text x="510" y="132" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">상대방</text>
<line x1="480" y1="128" x2="380" y2="128" stroke="#3282B8" stroke-width="2" stroke-dasharray="6 4" marker-end="url(#arr-{case_no})"/>
<polygon points="330,148 336,136 344,144 350,132 342,146 352,150 340,152 348,162 338,154 332,164 334,152 322,154 332,150 324,142" fill="#FFD200"/>
<text x="330" y="128" text-anchor="middle" fill="#ee3333" font-size="11" font-weight="700">충돌!</text>
</svg>'''


def svg_C(case_no):
    return f'''<svg viewBox="0 0 660 280" width="100%" style="max-width:660px">
<rect x="0" y="60" width="660" height="160" fill="#666"/>
<rect x="0" y="60" width="660" height="4" fill="#444"/><rect x="0" y="216" width="660" height="4" fill="#444"/>
<line x1="0" y1="138" x2="660" y2="138" stroke="#FFD200" stroke-width="2"/>
<line x1="0" y1="142" x2="660" y2="142" stroke="#FFD200" stroke-width="2"/>
<line x1="0" y1="178" x2="660" y2="178" stroke="#ddd" stroke-width="1" stroke-dasharray="12 8"/>
<text x="15" y="168" fill="#aaa" font-size="10">1차로</text><text x="15" y="200" fill="#aaa" font-size="10">2차로</text>
<rect x="520" y="68" width="130" height="18" rx="4" fill="rgba(0,0,0,0.5)"/><text x="585" y="81" text-anchor="middle" fill="#fff" font-size="10">고속도로</text>
<rect x="100" y="148" width="60" height="26" rx="6" fill="#DC3C37"/><text x="130" y="165" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">피고인</text>
<rect x="400" y="148" width="60" height="26" rx="6" fill="#3282B8"/><text x="430" y="165" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">상대방</text>
<polygon points="280,160 286,148 294,156 300,144 292,158 302,162 290,164 298,174 288,166 282,176 284,164 272,166 282,162 274,154" fill="#FFD200"/>
</svg>'''


def svg_D(case_no):
    return f'''<svg viewBox="0 0 660 340" width="100%" style="max-width:660px">
<defs><marker id="arr-{case_no}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round"/></marker></defs>
<rect x="0" y="120" width="660" height="110" fill="#666"/>
<line x1="0" y1="175" x2="260" y2="175" stroke="#FFD200" stroke-width="2"/>
<line x1="400" y1="175" x2="660" y2="175" stroke="#FFD200" stroke-width="2"/>
<rect x="295" y="122" width="70" height="8" fill="#fff" opacity="0.9"/><rect x="295" y="136" width="70" height="8" fill="#fff" opacity="0.9"/><rect x="295" y="150" width="70" height="8" fill="#fff" opacity="0.9"/><rect x="295" y="164" width="70" height="8" fill="#fff" opacity="0.9"/><rect x="295" y="178" width="70" height="8" fill="#fff" opacity="0.9"/><rect x="295" y="192" width="70" height="8" fill="#fff" opacity="0.9"/><rect x="295" y="206" width="70" height="8" fill="#fff" opacity="0.9"/>
<text x="330" y="115" text-anchor="middle" fill="#666" font-size="10">횡단보도</text>
<circle cx="330" cy="148" r="7" fill="#FFA94D"/><rect x="326" y="156" width="8" height="14" rx="2" fill="#FFA94D"/><text x="330" y="136" text-anchor="middle" fill="#FFA94D" font-size="10" font-weight="700">보행자</text>
<rect x="120" y="187" width="60" height="26" rx="6" fill="#DC3C37"/><text x="150" y="204" text-anchor="middle" fill="#fff" font-size="11" font-weight="700">피고인</text>
<line x1="180" y1="200" x2="280" y2="200" stroke="#DC3C37" stroke-width="2" stroke-dasharray="6 4" marker-end="url(#arr-{case_no})"/>
<polygon points="310,185 316,173 324,181 330,169 322,183 332,187 320,189 328,199 318,191 312,201 314,189 302,191 312,187 304,179" fill="#FFD200"/>
</svg>'''


def svg_E(case_no):
    return f'''<svg viewBox="0 0 660 200" width="100%" style="max-width:660px">
<rect x="0" y="60" width="660" height="80" fill="#7BA87B"/>
<rect x="0" y="60" width="660" height="3" fill="#5C8C5C"/><rect x="0" y="137" width="660" height="3" fill="#5C8C5C"/>
<line x1="0" y1="100" x2="660" y2="100" stroke="#a5cca5" stroke-width="1" stroke-dasharray="10 8"/>
<text x="50" y="105" fill="#dfe" font-size="14">&#8594;</text>
<rect x="250" y="44" width="160" height="16" rx="4" fill="#4a7a4a"/>
<text x="330" y="55" text-anchor="middle" fill="#fff" font-size="10">자전거도로</text>
<rect x="250" y="108" width="56" height="22" rx="5" fill="#DC3C37"/><text x="278" y="123" text-anchor="middle" fill="#fff" font-size="10" font-weight="700">피고인</text>
<rect x="320" y="78" width="44" height="22" rx="5" fill="#3282B8"/><text x="342" y="93" text-anchor="middle" fill="#fff" font-size="10" font-weight="700">甲</text>
</svg>'''


def svg_F(case_no):
    return f'''<svg viewBox="0 0 660 350" width="100%" style="max-width:660px">
<rect x="20" y="40" width="620" height="260" rx="12" fill="#e8e6de"/>
<rect x="60" y="230" width="90" height="40" rx="4" fill="#555"/>
<text x="105" y="254" text-anchor="middle" fill="#fff" font-size="10">지하주차장</text>
<text x="105" y="222" text-anchor="middle" fill="#666" font-size="10">출구 &#8593;</text>
<rect x="150" y="240" width="200" height="25" fill="#aaa"/>
<rect x="400" y="100" width="200" height="120" rx="10" fill="#d5d0c5"/>
<text x="500" y="155" text-anchor="middle" fill="#888" font-size="12">대학교/광장</text>
<rect x="180" y="243" width="56" height="22" rx="5" fill="#DC3C37"/><text x="208" y="258" text-anchor="middle" fill="#fff" font-size="10" font-weight="700">피고인</text>
<path d="M236 254 Q300 254 380 200 Q420 170 460 160" fill="none" stroke="#DC3C37" stroke-width="2.5" stroke-dasharray="6 4"/>
<circle cx="480" cy="160" r="7" fill="#FFA94D"/><rect x="476" y="168" width="8" height="14" rx="2" fill="#FFA94D"/>
<text x="480" y="148" text-anchor="middle" fill="#FFA94D" font-size="10">피해자</text>
</svg>'''


SVG_FUNCS = {'A': svg_A, 'B': svg_B, 'C': svg_C, 'D': svg_D, 'E': svg_E, 'F': svg_F}


def render(row):
    case_no = row['case_no']
    tpl_key = row['template'][0] if row['template'][0] in SVG_FUNCS else 'B'
    svg = SVG_FUNCS[tpl_key](case_no)
    vclass = verdict_class(row['verdict'])
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>사고상황도 — {case_no}</title>
{COMMON_STYLE}
</head>
<body>
<div class="wrap">
  <div class="title-bar">
    <h1>사고상황도 | {case_no}</h1>
    <span>템플릿 {row["template"]} · 판례 시각 자료</span>
  </div>
  <div class="summary">
    <b>핵심 배치</b><br>
    {row["desc"]}
  </div>
  <div class="diagram">
    {svg}
  </div>
  <div class="verdict {vclass}">
    <h2>판결: {row["verdict"]}</h2>
    <p>판결요지·법리 상세는 KoRoad 판례 AI 튜터(GPTs)에 사건번호 {case_no}로 질의하시면 자료 기반 답변을 받을 수 있습니다.</p>
  </div>
  <div class="footer">
    KoRoad 도로교통법 판례 시각 자료 · <a href="../viewer.html">📖 통합 조회</a> · <a href="../tutor/">📚 출근길 튜터</a> · <a href="./">📋 52건 목록</a>
  </div>
</div>
</body>
</html>'''


# 52개 + 인덱스 생성
OUT.mkdir(exist_ok=True)
for row in rows:
    (OUT / f"{row['case_no']}.html").write_text(render(row), encoding='utf-8')

idx_rows_html = ''.join(
    f'<tr><td><a href="{r["case_no"]}.html">{r["case_no"]}</a></td><td>{r["template"]}</td><td>{r["desc"]}</td><td>{r["verdict"]}</td></tr>'
    for r in rows
)
idx_html = f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>사고상황도 목록 — 52건</title>
<style>
body{{font-family:'Noto Sans KR',Arial,sans-serif;background:#f5f5f5;padding:20px;margin:0}}
.wrap{{max-width:900px;margin:0 auto;background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,0.08)}}
h1{{color:#1E2761;font-size:20px;margin-bottom:6px}}
.lead{{color:#666;font-size:13px;margin-bottom:18px;line-height:1.6}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#1E2761;color:#fff;padding:10px;text-align:left;font-weight:600}}
td{{padding:8px 10px;border-bottom:1px solid #eee}}
td a{{color:#7c3aed;text-decoration:none;font-weight:600}}
td a:hover{{text-decoration:underline}}
.footer{{margin-top:20px;text-align:center;font-size:11px;color:#888}}
.footer a{{color:#7c3aed;text-decoration:none}}
</style>
</head>
<body>
<div class="wrap">
<h1>📊 사고상황도 — 52건</h1>
<p class="lead">KoRoad 판례 AI 튜터(GPTs)에서 사건번호별 판결요지와 함께 참조하는 시각 자료입니다.<br>각 사건번호 클릭 → 사고상황도 페이지.</p>
<table>
<thead><tr><th>사건번호</th><th>템플릿</th><th>핵심 배치</th><th>판결</th></tr></thead>
<tbody>{idx_rows_html}</tbody>
</table>
<div class="footer">
<a href="../viewer.html">📖 통합 조회</a> · <a href="../tutor/">📚 출근길 튜터</a>
</div>
</div>
</body>
</html>'''
(OUT / 'index.html').write_text(idx_html, encoding='utf-8')

print(f'✅ {len(rows)}개 HTML + 1개 인덱스 생성 완료')
print(f'📁 폴더: {OUT.resolve()}')
