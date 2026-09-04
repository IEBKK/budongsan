"""seed/regions.json 재생성 스크립트.

행정표준코드관리시스템(code.go.kr)의 법정동코드 전체자료(현존)에서 시군구를 뽑고,
Nominatim(OSM)으로 중심좌표를 붙인다. 좌표는 지도 초기 배치/폴백용 근사값이면 충분하다.

    python -m pipeline.scripts.make_regions            # 다운로드부터 전부
    python -m pipeline.scripts.make_regions 파일.zip   # 받아둔 전체자료 재사용

Nominatim 은 초당 1회 제한이라 269개 시군구 기준 약 5분 걸린다.
좌표는 pipeline/cache/region_centroids.json 에 캐시되어 재실행 시 건너뛴다.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent.parent / "seed"
CACHE = Path(__file__).resolve().parent.parent / "cache" / "region_centroids.json"

CODE_DOWNLOAD = "https://www.code.go.kr/stdcode/regCodeFileDown.do?cPage=1&pageSize=99999"
CODE_FORM = (
    "cPage=1&regionCd_pk=&chkWantCnt=0&reqSggCd=&reqUmdCd=&reqRiCd=&searchOk="
    "&codeseId=00002&pageSize=10&regionCd=&locataddNm="
    "&sidoCd=*&sggCd=*&umdCd=*&riCd=*&disuseAt=0&stdate=&enddate="
)
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "budongsan-seed/1.0 (github.com/IEBKK/budongsan)"
XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# 2026 행정개편(전남광주통합특별시) 등 OSM 에 아직 없을 수 있는 명칭의 구명칭 폴백.
# 매칭용 별칭(aliases)도 여기서 나온다: 온비드 주소가 구명칭으로 올 수 있기 때문.
def legacy_full(sido: str, name: str) -> str | None:
    if sido == "전남광주통합특별시":
        return ("광주광역시 " if name.endswith("구") else "전라남도 ") + name
    if sido == "강원특별자치도":
        return "강원도 " + name
    if sido == "전북특별자치도":
        return "전라북도 " + name
    return None


def download_codes() -> bytes:
    req = urllib.request.Request(
        CODE_DOWNLOAD,
        data=CODE_FORM.encode(),
        headers={"Referer": "https://www.code.go.kr/stdcode/regCodeL.do", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def parse_codes(blob: bytes) -> list[dict]:
    outer = zipfile.ZipFile(BytesIO(blob))
    xlsx = zipfile.ZipFile(BytesIO(outer.read(outer.namelist()[0])))
    root = ET.fromstring(xlsx.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in root.iter(XLSX_NS + "row"):
        vals = ["".join(t.text or "" for t in c.iter(XLSX_NS + "t")) for c in row.iter(XLSX_NS + "c")]
        if len(vals) >= 2 and re.match(r"^\d{10}$", vals[0]):
            rows.append(vals)

    sido_by_prefix = {r[0][:2]: r[1] for r in rows if r[0][2:] == "00000000"}
    out = []
    for code10, full in rows:
        if code10[5:] != "00000" or code10[2:5] == "000":
            continue  # 시군구 레벨만
        sido = sido_by_prefix.get(code10[:2], "")
        if not sido:  # 세종처럼 시도 행이 따로 없는 단층 구조
            sido = full
        name = full[len(sido):].strip() or full
        entry: dict = {"code": code10[:5], "sido": sido, "name": name}
        legacy = legacy_full(sido, name)
        if legacy:
            entry["aliases"] = [legacy.split()[0]]
        out.append(entry)

    # 구가 있는 시(수원시 41110 등)는 모(母) 코드와 구 코드가 둘 다 현존하지만,
    # 실거래 데이터는 구 코드에 등록되므로 모 코드는 제외한다.
    # (영동군 43740/증평군 43745 처럼 코드만 이웃인 경우가 있어 이름으로 판별한다.)
    has_gu = {
        (p["sido"], p["name"])
        for p in out
        for q in out
        if p is not q and q["sido"] == p["sido"] and q["name"].startswith(p["name"] + " ")
    }
    return [r for r in out if (r["sido"], r["name"]) not in has_gu]


def geocode(query: str) -> tuple[float, float] | None:
    url = NOMINATIM + "?" + urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "kr"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            hits = json.loads(r.read())
    except Exception:
        return None
    if not hits:
        return None
    lat, lng = float(hits[0]["lat"]), float(hits[0]["lon"])
    if not (33.0 <= lat <= 39.7 and 124.0 <= lng <= 132.0):
        return None
    return lat, lng


def main() -> None:
    blob = Path(sys.argv[1]).read_bytes() if len(sys.argv) > 1 else download_codes()
    regions = parse_codes(blob)
    print(f"시군구 {len(regions)}개")

    cache: dict[str, list[float]] = {}
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    missing = []
    for r in regions:
        if r["code"] in cache:
            continue
        full = f"{r['sido']} {r['name']}" if r["sido"] != r["name"] else r["sido"]
        queries = [q for q in (legacy_full(r["sido"], r["name"]), full, r["name"]) if q]
        for q in queries:
            hit = geocode(q)
            time.sleep(1.1)  # Nominatim 정책: 초당 1회
            if hit:
                cache[r["code"]] = [round(hit[0], 4), round(hit[1], 4)]
                print(f"  {r['code']} {full} ← '{q}' {cache[r['code']]}")
                break
        else:
            missing.append(r)
            print(f"  {r['code']} {full} ← 실패")
        CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")

    if missing:
        print(f"좌표 실패 {len(missing)}건 — 수동으로 cache 에 채운 뒤 재실행하라:")
        for r in missing:
            print(f"  {r['code']} {r['sido']} {r['name']}")
        raise SystemExit(1)

    for r in regions:
        r["lat"], r["lng"] = cache[r["code"]]
    payload = {
        "note": "시군구(법정동 5자리) 코드 + 근사 중심좌표. pipeline/scripts/make_regions.py 로 재생성한다. "
        "좌표는 지도 초기 배치/폴백용 근사값이며, 개별 물건 좌표는 geocode.py가 채운다. "
        "aliases 는 행정개편 구명칭 매칭용(온비드 주소 대응).",
        "regions": regions,
    }
    out = SEED_DIR / "regions.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{out} 갱신 완료 ({len(regions)}개)")


if __name__ == "__main__":
    main()
