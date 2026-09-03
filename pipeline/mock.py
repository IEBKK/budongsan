"""API 키 없이 프런트엔드를 개발/검증하기 위한 합성 데이터 생성기.

실제 수집 경로와 동일한 Trade / AuctionThing 객체를 만들어 내므로, 키가 생기면
build.py 의 소스 함수만 바꾸면 되고 집계·산출 코드는 그대로 쓴다.
운영 파이프라인(daily-data.yml)에서는 절대 사용하지 않는다.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from .sources.common import Trade
from .sources.onbid import AuctionThing

PYEONG = 3.3058

# 시군구별 대략적 가격대를 흉내내기 위한 가중치
_TIER = {"11680": 1.0, "11650": 0.95, "11710": 0.85, "11170": 0.8, "11440": 0.7}


def _tier(region) -> float:
    return _TIER.get(region.code, 0.45 + (int(region.code[-2:]) % 7) * 0.05)


def _umds(region, rng) -> list[str]:
    """합성 데이터임이 드러나도록 법정동은 시군구 이름에서 파생시킨다."""
    stem = region.name[:-1] if region.name[-1] in "구시군" else region.name
    return [f"{stem}{i}동" for i in range(1, 6)]


def _drift(mi: int, total: int, rng) -> float:
    return 1 + (mi - total / 2) * 0.008 + rng.uniform(-0.006, 0.006)


# ── 아파트 ────────────────────────────────────────────────────────────

_APT_PREFIX = ["래미안", "자이", "푸르지오", "e편한세상", "힐스테이트", "아이파크", "롯데캐슬", "한신", "우성", "삼성"]
_APT_SUFFIX = ["1차", "2차", "리버뷰", "센트럴", "파크", "타워", "스카이", "포레스트"]
_APT_AREAS = [39.6, 49.5, 59.98, 74.5, 84.98, 101.9, 114.8, 134.9]


def generate(region, months: list[str], seed: int = 20260824) -> list[Trade]:
    """아파트 매매 (기존 호출부 호환을 위해 이름 유지)."""
    rng = random.Random(f"{seed}-apt-{region.code}")
    base_ppp = 4200 * _tier(region)
    umds = _umds(region, rng)

    complexes = [
        {
            "name": rng.choice(_APT_PREFIX) + rng.choice(_APT_SUFFIX),
            "umd": rng.choice(umds),
            "jibun": str(rng.randint(100, 1400)),
            "build": rng.randint(1985, 2024),
            "road": rng.choice(["테헤란로", "선릉로", "올림픽로", "중앙로", "시청로"]),
            "factor": rng.uniform(0.75, 1.35),
            "areas": rng.sample(_APT_AREAS, rng.randint(2, 4)),
        }
        for _ in range(rng.randint(14, 26))
    ]

    deals: list[Trade] = []
    for mi, ym in enumerate(months):
        drift = _drift(mi, len(months), rng)
        for c in complexes:
            for _ in range(rng.randint(0, 4)):
                area = rng.choice(c["areas"])
                ppp = base_ppp * c["factor"] * drift * rng.uniform(0.93, 1.07)
                deals.append(
                    Trade(
                        sgg_code=region.code,
                        umd=c["umd"],
                        jibun=c["jibun"],
                        name=c["name"],
                        build_year=c["build"],
                        area=area,
                        floor=rng.randint(1, 28),
                        amount=int(ppp * (area / PYEONG) / 100) * 100,
                        ym=ym,
                        day=rng.randint(1, 28),
                        road_name=c["road"],
                    )
                )
    return deals


generate_apt = generate


# ── 상가 (상업업무용) ──────────────────────────────────────────────────

_USES = ["제1종근린생활시설", "제2종근린생활시설", "판매시설", "업무시설", "숙박시설"]
_LAND_USES = ["일반상업지역", "근린상업지역", "준주거지역", "제3종일반주거지역", "준공업지역"]


def generate_commercial(region, months: list[str], seed: int = 20260824) -> list[Trade]:
    rng = random.Random(f"{seed}-cmr-{region.code}")
    # 상업용은 아파트보다 평단가 편차가 크고 대체로 낮게 잡는다.
    base_ppp = 2600 * _tier(region)
    umds = _umds(region, rng)

    buildings = []
    for _ in range(rng.randint(8, 16)):
        use = rng.choice(_USES)
        jibun = str(rng.randint(100, 1400))
        buildings.append(
            {
                "use": use,
                "name": f"{use} {jibun}",
                "umd": rng.choice(umds),
                "jibun": jibun,
                "build": rng.randint(1980, 2022),
                "type": rng.choice(["집합", "일반"]),
                "landUse": rng.choice(_LAND_USES),
                "factor": rng.uniform(0.6, 1.9),
                "area": rng.choice([42.5, 66.1, 99.2, 132.4, 231.0, 410.9, 826.4]),
            }
        )

    deals: list[Trade] = []
    for mi, ym in enumerate(months):
        drift = _drift(mi, len(months), rng)
        for b in buildings:
            for _ in range(rng.randint(0, 2)):
                area = round(b["area"] * rng.uniform(0.85, 1.15), 2)
                ppp = base_ppp * b["factor"] * drift * rng.uniform(0.9, 1.1)
                deals.append(
                    Trade(
                        sgg_code=region.code,
                        umd=b["umd"],
                        jibun=b["jibun"],
                        name=b["name"],
                        build_year=b["build"],
                        area=area,
                        floor=rng.randint(1, 12),
                        amount=int(ppp * (area / PYEONG) / 100) * 100,
                        ym=ym,
                        day=rng.randint(1, 28),
                        road_name=rng.choice(["테헤란로", "강남대로", "중앙로", "시청로"]),
                        extra={
                            "use": b["use"],
                            "buildingType": b["type"],
                            "landUse": b["landUse"],
                            "plottageAr": round(area * rng.uniform(0.3, 0.9), 1),
                        },
                    )
                )
    return deals


# ── 토지 ──────────────────────────────────────────────────────────────

_JIMOK = ["대", "전", "답", "임야", "잡종지", "주차장", "창고용지"]
_JIMOK_TIER = {"대": 1.0, "잡종지": 0.5, "주차장": 0.55, "창고용지": 0.45, "전": 0.25, "답": 0.2, "임야": 0.08}


def generate_land(region, months: list[str], seed: int = 20260824) -> list[Trade]:
    rng = random.Random(f"{seed}-land-{region.code}")
    base_ppp = 3100 * _tier(region)
    umds = _umds(region, rng)

    parcels = [
        {
            "umd": rng.choice(umds),
            "jimok": rng.choice(_JIMOK),
            "landUse": rng.choice(_LAND_USES + ["자연녹지지역", "생산녹지지역"]),
        }
        for _ in range(rng.randint(6, 12))
    ]

    deals: list[Trade] = []
    for mi, ym in enumerate(months):
        drift = _drift(mi, len(months), rng)
        for p in parcels:
            for _ in range(rng.randint(0, 2)):
                area = round(rng.uniform(80, 2200), 1)
                ppp = base_ppp * _JIMOK_TIER[p["jimok"]] * drift * rng.uniform(0.8, 1.2)
                share = "지분" if rng.random() < 0.25 else ""
                deals.append(
                    Trade(
                        sgg_code=region.code,
                        umd=p["umd"],
                        jibun="",  # 토지 API 는 지번 미제공
                        name=f"{p['umd']} {p['jimok']}",
                        build_year=None,
                        area=area,
                        floor=None,
                        amount=int(ppp * (area / PYEONG) / 100) * 100,
                        ym=ym,
                        day=rng.randint(1, 28),
                        extra={
                            "jimok": p["jimok"],
                            "landUse": p["landUse"],
                            "shareType": share,
                        },
                    )
                )
    return deals


# ── 공매 (온비드) ──────────────────────────────────────────────────────

_CATEGORIES = [
    ("부동산 / 주거용건물 / 아파트", 1.0),
    ("부동산 / 주거용건물 / 다세대주택", 0.55),
    ("부동산 / 상가용건물 / 근린생활시설", 0.8),
    ("부동산 / 토지 / 대지", 0.6),
    ("부동산 / 토지 / 임야", 0.15),
]


def generate_auction(regions: list, today: date | None = None, seed: int = 20260824) -> list[AuctionThing]:
    """전국 단위 API 지만, seed 범위(현재 서울) 물건만 만들어 낸다."""
    rng = random.Random(f"{seed}-auction")
    today = today or date.today()
    things: list[AuctionThing] = []

    for region in regions:
        stem = region.name[:-1] if region.name[-1] in "구시군" else region.name
        for n in range(rng.randint(1, 5)):
            category, cat_tier = rng.choice(_CATEGORIES)
            appraisal = int(rng.uniform(1.2, 28.0) * 1e8 * cat_tier * _tier(region))
            # 유찰이 쌓일수록 최저가가 10%씩 깎인다 — 실제 공매 진행 방식.
            # 장기 유찰(7회, 감정가 48%)까지 롱테일을 둬야 최저가율 필터 전 구간이 검증된다.
            fails = rng.choices(range(8), weights=[30, 24, 18, 12, 7, 4, 3, 2])[0]
            min_bid = int(appraisal * (0.9 ** fails))
            begin = today + timedelta(days=rng.randint(1, 21))
            close = begin + timedelta(days=2)
            umd = f"{stem}{rng.randint(1, 5)}동"
            things.append(
                AuctionThing(
                    key=f"2026{rng.randint(10, 99)}-{region.code}{n:02d}-1",
                    name=f"{region.sido[:2]} {region.name} {umd} {category.split(' / ')[-1]}",
                    category=category,
                    address=f"{region.sido} {region.name} {umd} {rng.randint(100, 1400)}-{rng.randint(1, 30)}",
                    min_bid=min_bid,
                    appraisal=appraisal,
                    fail_count=fails,
                    begin_at=f"{begin.isoformat()}T10:00",
                    close_at=f"{close.isoformat()}T17:00",
                    status="입찰진행중",
                    disposal="매각",
                    bid_method="인터넷",
                    institution="한국자산관리공사",
                    extra={"mgmtNo": f"2026-{region.code}-{n:04d}"},
                )
            )
    return things
