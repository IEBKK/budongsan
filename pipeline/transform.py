"""수집한 원자료를 프런트가 그대로 그릴 수 있는 형태로 집계한다.

TRND-05/PICK-01 원칙과 동일하게, 클라이언트 계산을 최소화하기 위해
단지별 집계·면적 타입별 통계·시계열을 전부 여기서 만들어 둔다.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Callable, Iterable

PYEONG = 3.3058  # m2 -> 평

GeoResolver = Callable[[object], tuple[float, float, str]]


def median(values: list[float]) -> float:
    if not values:
        return 0
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def price_per_pyeong(amount_manwon: int, area_m2: float) -> float:
    if area_m2 <= 0:
        return 0
    return round(amount_manwon / (area_m2 / PYEONG), 1)


def complex_id(sgg: str, umd: str, jibun: str, name: str) -> str:
    key = f"{sgg}|{umd}|{jibun}|{name}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def area_label(area_m2: float) -> str:
    return f"{area_m2:.2f}".rstrip("0").rstrip(".")


# 아파트는 면적 타입이 사실상 이산적(84.98㎡ 등)이라 정확한 값으로 묶는다.
# 상가·토지 면적은 연속값이라 그대로 묶으면 전부 1건짜리 그룹이 되므로 구간으로 버킷팅한다.
_PYEONG_BUCKETS = [
    (10, "10평 미만"),
    (30, "10~30평"),
    (100, "30~100평"),
    (300, "100~300평"),
    (float("inf"), "300평 이상"),
]


def bucket_label(area_m2: float) -> str:
    py = area_m2 / PYEONG
    for upper, label in _PYEONG_BUCKETS:
        if py < upper:
            return label
    return _PYEONG_BUCKETS[-1][1]


def _group_label(kind: str, area_m2: float) -> str:
    return area_label(area_m2) if kind == "apt" else bucket_label(area_m2)


def build_trade_items(deals: Iterable, region, resolve_geo: GeoResolver, kind: str = "apt") -> list[dict]:
    """실거래 목록 -> 지도 마커 1개 단위로 집계한다.

    묶는 단위는 유형마다 다르지만 키 구조는 (법정동, 지번, 이름) 하나로 통일된다.
      - apt        : 법정동 × 지번 × 단지명   → 단지
      - commercial : 법정동 × 지번 × 건물명   → 건물
      - land       : 법정동 × 지목 (지번 미제공) → 법정동·지목 묶음
    """
    grouped: dict[tuple[str, str, str], list] = defaultdict(list)
    for d in deals:
        grouped[(d.umd, d.jibun, d.name)].append(d)

    out: list[dict] = []
    for (umd, jibun, name), items in grouped.items():
        items.sort(key=lambda d: (d.ym, d.day), reverse=True)
        lat, lng, geo_kind = resolve_geo(items[0])

        by_area: dict[str, list] = defaultdict(list)
        for d in items:
            by_area[_group_label(kind, d.area)].append(d)

        areas = []
        for label, ds in sorted(by_area.items(), key=lambda kv: min(d.area for d in kv[1])):
            amounts = [d.amount for d in ds]
            areas.append(
                {
                    "label": label,
                    "areaM2": round(median([d.area for d in ds]), 2),
                    "pyeong": round(median([d.area for d in ds]) / PYEONG, 1),
                    "count": len(ds),
                    "medianAmount": int(median(amounts)),
                    "minAmount": min(amounts),
                    "maxAmount": max(amounts),
                    "pricePerPyeong": price_per_pyeong(int(median(amounts)), ds[0].area),
                }
            )

        monthly: dict[str, list[int]] = defaultdict(list)
        for d in items:
            monthly[d.ym].append(price_per_pyeong(d.amount, d.area))
        series = [
            {"ym": ym, "count": len(v), "pricePerPyeong": round(median(v), 1)}
            for ym, v in sorted(monthly.items())
        ]

        all_amounts = [d.amount for d in items]
        all_areas = [d.area for d in items]
        out.append(
            {
                "kind": kind,
                "id": complex_id(region.code, umd, jibun, name),
                "name": name,
                "umd": umd,
                "jibun": jibun,
                "roadName": items[0].road_name,
                "buildYear": items[0].build_year,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "geo": geo_kind,
                "dealCount": len(items),
                "medianAmount": int(median(all_amounts)),
                "minAmount": min(all_amounts),
                "maxAmount": max(all_amounts),
                "pricePerPyeong": round(
                    median([price_per_pyeong(d.amount, d.area) for d in items]), 1
                ),
                "lastYm": items[0].ym,
                "medianArea": round(median(all_areas), 2),
                "minArea": round(min(all_areas), 2),
                "maxArea": round(max(all_areas), 2),
                # 유형별 고유 항목 (상가: 용도/유형/용도지역, 토지: 지목/용도지역)
                "extra": {k: v for k, v in items[0].extra.items() if v not in (None, "")},
                "areas": areas,
                "series": series,
                "deals": [
                    {
                        "ym": d.ym,
                        "day": d.day,
                        "amount": d.amount,
                        "area": round(d.area, 2),
                        "floor": d.floor,
                        **({"share": d.extra["shareType"]} if d.extra.get("shareType") else {}),
                    }
                    for d in items[:60]  # 파일 크기 상한(3.4) 유지: 항목당 최근 60건
                ],
            }
        )

    out.sort(key=lambda c: (-c["dealCount"], c["name"]))
    return out


# 이전 이름 호환 (아파트 전용으로 쓰던 시절의 호출부·테스트)
def build_complexes(deals: Iterable, region, resolve_geo: GeoResolver) -> list[dict]:
    return build_trade_items(deals, region, resolve_geo, kind="apt")


def build_region_summary(region, complexes: list[dict], months: list[str]) -> dict:
    """시군구 1건짜리 전국 요약 레코드 (초기 지도 로딩용)."""
    deal_count = sum(c["dealCount"] for c in complexes)
    ppp = [c["pricePerPyeong"] for c in complexes if c["pricePerPyeong"] > 0]

    per_month: dict[str, list[float]] = {ym: [] for ym in months}
    month_counts: dict[str, int] = {ym: 0 for ym in months}
    for c in complexes:
        for point in c["series"]:
            if point["ym"] in per_month:
                per_month[point["ym"]].append(point["pricePerPyeong"])
                month_counts[point["ym"]] += point["count"]

    monthly = [
        {
            "ym": ym,
            "count": month_counts[ym],
            "pricePerPyeong": round(median(per_month[ym]), 1),
        }
        for ym in months
    ]

    mom = None
    if len(monthly) >= 2:
        prev, cur = monthly[-2]["pricePerPyeong"], monthly[-1]["pricePerPyeong"]
        if prev > 0:
            mom = round((cur - prev) / prev * 100, 2)

    return {
        "code": region.code,
        "sido": region.sido,
        "name": region.name,
        "lat": region.lat,
        "lng": region.lng,
        "complexCount": len(complexes),
        "dealCount": deal_count,
        "pricePerPyeong": round(median(ppp), 1),
        "medianAmount": int(median([c["medianAmount"] for c in complexes])) if complexes else 0,
        "momPct": mom,
        "monthly": monthly,
    }


def build_search_index(region, complexes: list[dict]) -> list[dict]:
    """검색 인덱스는 전국 1파일이므로 필드를 짧게 유지한다 (3.3)."""
    return [
        {
            "i": c["id"],
            "n": c["name"],
            "a": f"{region.name} {c['umd']}",
            "c": region.code,
            "y": c["lat"],
            "x": c["lng"],
        }
        for c in complexes
    ]


# ── 경매·공매 (PRD 3.2-D Phase 1: 온비드 공매) ──────────────────────────

def build_auction_items(
    things: Iterable,
    regions: list,
    resolve_geo,
    seen: dict[str, str],
    today: str,
) -> tuple[list[dict], int]:
    """공매 물건 -> 지도 항목. (항목 목록, 좌표 미부여로 제외된 건수) 를 돌려준다.

    seen 은 '물건키 -> 최초 관측일' 캐시다. 온비드 응답에는 '신규' 표시가 없으므로,
    우리가 처음 본 날을 기록해 두고 그것으로 NEW 뱃지를 판정한다(PRD 3.2-D).
    """
    from .config import region_by_address

    out: list[dict] = []
    skipped = 0
    for t in things:
        region = region_by_address(regions, t.address)
        if region is None:
            # seed 범위 밖 물건은 좌표를 붙일 수 없다.
            skipped += 1
            continue

        first_seen = seen.setdefault(t.key, today)
        umd, jibun = _split_address(t.address, region.name)
        lat, lng, geo_kind = resolve_geo(region, umd, jibun)

        out.append(
            {
                "kind": "auction",
                "id": hashlib.sha1(t.key.encode("utf-8")).hexdigest()[:10],
                "key": t.key,
                "name": t.name,
                "category": t.category,
                "address": t.address,
                "regionCode": region.code,
                "regionName": region.name,
                "umd": umd,
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "geo": geo_kind,
                # 온비드는 원 단위, 나머지 유형은 만원 단위 → 만원으로 통일한다.
                "minBid": round(t.min_bid / 10000),
                "appraisal": round(t.appraisal / 10000),
                "bidRate": t.bid_rate,
                "failCount": t.fail_count,
                "beginAt": t.begin_at,
                "closeAt": t.close_at,
                "status": t.status,
                "disposal": t.disposal,
                "bidMethod": t.bid_method,
                "institution": t.institution,
                "firstSeen": first_seen,
                "isNew": first_seen == today,
                "extra": {k: v for k, v in t.extra.items() if v not in (None, "")},
            }
        )

    # 유찰이 쌓여 최저가율이 낮은 물건일수록 먼저 (추천 엔진의 P0 시그널과 같은 정렬)
    out.sort(key=lambda i: (i["bidRate"] if i["bidRate"] is not None else 999, -i["failCount"]))
    return out, skipped


def _split_address(address: str, sgg_name: str) -> tuple[str, str]:
    """'서울특별시 강남구 역삼동 725-10' -> ('역삼동', '725-10')"""
    parts = address.split()
    if sgg_name in parts:
        rest = parts[parts.index(sgg_name) + 1 :]
    else:
        rest = parts[2:]
    umd = rest[0] if rest else ""
    jibun = rest[1] if len(rest) > 1 else ""
    return umd, jibun


def build_auction_summary(items: list[dict]) -> dict:
    """TRND-03 대비: 공매 핵심 지표 카드용 사전 집계."""
    rates = [i["bidRate"] for i in items if i["bidRate"] is not None]
    fails = [i["failCount"] for i in items]
    return {
        "count": len(items),
        "newCount": sum(1 for i in items if i["isNew"]),
        "avgBidRate": round(sum(rates) / len(rates), 1) if rates else None,
        "medianBidRate": round(median(rates), 1) if rates else None,
        "avgFailCount": round(sum(fails) / len(fails), 2) if fails else 0,
    }
