"""검색 유입용 정적 페이지 생성 (SEO).

시군구별 요약 페이지(web/public/r/<code>.html)와 sitemap.xml 을 만든다.
SPA 는 검색엔진에 잡힐 콘텐츠가 없으므로, '〇〇구 아파트 실거래가' 류의
롱테일 검색이 랜딩할 정적 페이지를 데이터에서 매일 재생성한다.
"""
from __future__ import annotations

import html
import json
from datetime import date

from . import config

SITE = "https://iebkk.github.io/budongsan"
KIND_LABEL = {"apt": "아파트", "commercial": "상가", "land": "토지"}

PAGE_TMPL = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{site}/og.png">
<meta property="og:locale" content="ko_KR">
<style>
body{{font-family:-apple-system,'Apple SD Gothic Neo','Malgun Gothic',sans-serif;margin:0;color:#16191d;background:#f6f7f9}}
main{{max-width:720px;margin:0 auto;padding:32px 20px 60px}}
h1{{font-size:24px;margin:0 0 4px}}
.sub{{color:#6b7280;font-size:14px;margin:0 0 20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:18px 0}}
.card{{background:#fff;border:1px solid #e4e7ec;border-radius:10px;padding:14px 16px}}
.card h2{{font-size:13px;color:#6b7280;margin:0 0 6px;font-weight:600}}
.card p{{margin:2px 0;font-size:14px}}
.card b{{font-variant-numeric:tabular-nums}}
.cta{{display:inline-block;margin-top:18px;background:#2563eb;color:#fff;text-decoration:none;
padding:11px 20px;border-radius:9px;font-weight:700}}
footer{{margin-top:32px;font-size:12px;color:#6b7280;line-height:1.6}}
a{{color:#2563eb}}
</style>
</head>
<body>
<main>
<h1>{h1}</h1>
<p class="sub">최근 3개월 실거래 · 공공데이터 기준 {asof} · 매일 자동 갱신</p>
<div class="grid">{cards}</div>
<p>지도에서 단지별 실거래 내역, 온비드 공매 물건, 매일 갱신되는 급매 신호와
수익 스크리너를 무료로 확인할 수 있습니다.</p>
<a class="cta" href="{site}/">지도에서 {name} 보기 →</a>
<footer>
출처: 국토교통부 실거래가 공개시스템 · 온비드(한국자산관리공사) (공공데이터포털)<br>
본 페이지의 정보는 참고용이며, 거래·입찰 전 원출처 확인이 필요합니다.<br>
© 2026 IEBKK. All rights reserved. · <a href="{site}/">부동산 통합 모니터링</a>
</footer>
</main>
</body>
</html>
"""


def _fmt_eok(man: float) -> str:
    return f"{man/10000:.1f}억" if man >= 10000 else f"{man:,.0f}만"


def build_seo_pages(today: date) -> int:
    """시군구 페이지 + sitemap.xml 생성. 만든 페이지 수를 돌려준다."""
    out_root = config.OUT_DIR.parent  # web/public
    pages_dir = out_root / "r"
    pages_dir.mkdir(parents=True, exist_ok=True)

    summaries = {}
    for kind in KIND_LABEL:
        p = config.OUT_DIR / "summary" / f"{kind}.json"
        if p.exists():
            for r in json.loads(p.read_text(encoding="utf-8"))["regions"]:
                summaries.setdefault(r["code"], {})[kind] = r

    urls = [f"{SITE}/"]
    count = 0
    for code, kinds in sorted(summaries.items()):
        any_r = next(iter(kinds.values()))
        full = f"{any_r['sido']} {any_r['name']}" if any_r["sido"] != any_r["name"] else any_r["sido"]
        name = any_r["name"]
        cards = []
        desc_bits = []
        for kind, label in KIND_LABEL.items():
            r = kinds.get(kind)
            if not r or not r.get("dealCount"):
                continue
            lines = [f"<p>최근 3개월 거래 <b>{r['dealCount']:,}건</b></p>"]
            if r.get("medianAmount"):
                lines.append(f"<p>중위 거래가 <b>{_fmt_eok(r['medianAmount'])}</b></p>")
            if r.get("pricePerPyeong"):
                lines.append(f"<p>평당가 <b>{r['pricePerPyeong']:,.0f}만</b></p>")
            if kind == "apt" and r.get("complexCount"):
                lines.append(f"<p>거래 단지 <b>{r['complexCount']}곳</b></p>")
            cards.append(f'<div class="card"><h2>{label} 실거래</h2>{"".join(lines)}</div>')
            desc_bits.append(f"{label} {r['dealCount']:,}건")
        if not cards:
            continue

        title = f"{full} 아파트·상가·토지 실거래가와 공매 | 부동산 통합 모니터링"
        desc = (
            f"{full} 최근 3개월 실거래 — {', '.join(desc_bits)}. "
            "온비드 공매와 급매 신호까지 지도에서 무료로 확인하세요. 매일 갱신."
        )
        url = f"{SITE}/r/{code}.html"
        page = PAGE_TMPL.format(
            title=html.escape(title), desc=html.escape(desc), url=url, site=SITE,
            h1=html.escape(f"{full} 실거래가 · 공매 현황"), name=html.escape(name),
            asof=today.isoformat(), cards="".join(cards),
        )
        (pages_dir / f"{code}.html").write_text(page, encoding="utf-8")
        urls.append(url)
        count += 1

    lastmod = today.isoformat()
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        sitemap.append(f"<url><loc>{u}</loc><lastmod>{lastmod}</lastmod></url>")
    sitemap.append("</urlset>")
    (out_root / "sitemap.xml").write_text("\n".join(sitemap), encoding="utf-8")

    print(f"  SEO: 시군구 페이지 {count}개 + sitemap.xml ({len(urls)} URL)")
    return count
