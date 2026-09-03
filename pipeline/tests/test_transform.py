"""의존성 없이 실행되는 스모크 테스트: python3 -m pipeline.tests.test_transform"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from .. import transform
from ..config import Region, region_by_address, rolling_months
from ..sources import molit_apt, molit_commercial, molit_land, onbid

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

GANGNAM = Region(code="11680", sido="서울특별시", name="강남구", lat=37.5172, lng=127.0473)
REGIONS = [GANGNAM]


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def flat_geo(_deal):
    return (GANGNAM.lat, GANGNAM.lng, "approx")


def region_geo(region, _umd, _jibun):
    return (region.lat, region.lng, "approx")


failures: list[str] = []


def check(label: str, actual, expected) -> None:
    if actual != expected:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")


def test_apt() -> None:
    deals = molit_apt.parse(fixture("apt_trade_sample.xml"))
    check("[apt] 해제 거래 제외 후 건수", len(deals), 3)
    check("[apt] 콤마 포함 금액 파싱", deals[0].amount, 350000)
    check("[apt] 전용면적 파싱", deals[0].area, 84.98)
    check("[apt] 거래연월", deals[0].ym, "202606")
    check("[apt] 한글 태그 호환 - 단지명", deals[2].name, "은마")
    check("[apt] 한글 태그 호환 - 금액", deals[2].amount, 271500)
    check("[apt] 법정동 공백 제거", deals[2].umd, "대치동")
    check("[apt] 해제건 제외 확인", [d.name for d in deals].count("은마"), 1)

    items = transform.build_trade_items(deals, GANGNAM, flat_geo, kind="apt")
    check("[apt] 집계 항목 수", len(items), 2)
    palace = next(c for c in items if c["name"] == "래미안대치팰리스")
    check("[apt] 거래건수", palace["dealCount"], 2)
    check("[apt] 면적 타입은 실면적으로 분리", len(palace["areas"]), 2)
    check("[apt] ID 결정성", palace["id"], transform.complex_id("11680", "대치동", "670", "래미안대치팰리스"))
    check("[apt] 최근 거래연월", palace["lastYm"], "202606")
    check("[apt] kind", palace["kind"], "apt")
    a85 = next(a for a in palace["areas"] if a["label"] == "84.98")
    check("[apt] 면적별 중위가", a85["medianAmount"], 350000)


def test_commercial() -> None:
    deals = molit_commercial.parse(fixture("commercial_trade_sample.xml"))
    check("[상가] 해제 거래 제외 후 건수", len(deals), 3)
    check("[상가] 건물면적 파싱", deals[0].area, 132.45)
    check("[상가] 건물명 없으면 용도+지번으로 합성", deals[1].name, "업무시설 737")
    check("[상가] 용도지역", deals[0].extra["landUse"], "일반상업지역")
    check("[상가] 대지면적", deals[0].extra["plottageAr"], 48.2)
    check("[상가] 한글 태그 호환 - 용도", deals[2].extra["use"], "제2종근린생활시설")
    check("[상가] 한글 태그 호환 - 금액", deals[2].amount, 41500)

    items = transform.build_trade_items(deals, GANGNAM, flat_geo, kind="commercial")
    check("[상가] 집계 항목 수", len(items), 3)
    check("[상가] kind", items[0]["kind"], "commercial")
    check("[상가] extra 보존", items[0]["extra"].get("landUse") is not None, True)
    # 연속값 면적은 구간으로 묶인다
    office = next(c for c in items if c["name"] == "업무시설 737")
    check("[상가] 면적 구간 라벨", office["areas"][0]["label"], "100~300평")


def test_land() -> None:
    deals = molit_land.parse(fixture("land_trade_sample.xml"))
    check("[토지] 건수", len(deals), 3)
    check("[토지] 거래면적", deals[0].area, 331.4)
    check("[토지] 지목", deals[0].extra["jimok"], "대")
    check("[토지] 지번 미제공", deals[0].jibun, "")
    check("[토지] 표시명 = 법정동 + 지목", deals[0].name, "자곡동 대")
    check("[토지] 지분거래 구분", deals[0].extra["shareType"], "지분")
    check("[토지] 한글 태그 호환 - 지목", deals[2].extra["jimok"], "전")
    check("[토지] 층 개념 없음", deals[0].floor, None)

    items = transform.build_trade_items(deals, GANGNAM, flat_geo, kind="land")
    check("[토지] 법정동×지목 단위로 묶임", len(items), 2)
    daeji = next(c for c in items if c["name"] == "자곡동 대")
    check("[토지] 묶인 거래건수", daeji["dealCount"], 2)
    check("[토지] 면적 범위", (daeji["minArea"], daeji["maxArea"]), (150.0, 331.4))
    # 거래는 최신순 정렬 → 지분거래(6월)는 7월 건 뒤에 온다
    check("[토지] 거래 최신순 정렬", [d["ym"] for d in daeji["deals"]], ["202607", "202606"])
    check("[토지] 지분거래 표시 보존", [d.get("share") for d in daeji["deals"]], [None, "지분"])


def test_auction() -> None:
    things = onbid.parse(fixture("onbid_sample.xml"))
    check("[공매] 주소 없는 건 제외", len(things), 2)
    seoul = things[0]
    check("[공매] 물건키", seoul.key, "202601-00001-1001-1")
    check("[공매] 최저가", seoul.min_bid, 612000000)
    check("[공매] 감정가", seoul.appraisal, 1200000000)
    check("[공매] 최저가율", seoul.bid_rate, 51.0)
    check("[공매] 유찰횟수", seoul.fail_count, 3)
    check("[공매] 마감일시 ISO 변환", seoul.close_at, "2026-09-09T17:00")

    seen: dict[str, str] = {}
    items, skipped = transform.build_auction_items(things, REGIONS, region_geo, seen, "2026-08-30")
    check("[공매] seed 범위 밖(부산) 제외", skipped, 1)
    check("[공매] 남은 항목", len(items), 1)
    check("[공매] 원 -> 만원 변환", items[0]["minBid"], 61200)
    check("[공매] 법정동 추출", items[0]["umd"], "역삼동")
    check("[공매] 첫 관측이므로 NEW", items[0]["isNew"], True)

    # 다음 날 같은 물건을 다시 보면 NEW 가 아니어야 한다
    items2, _ = transform.build_auction_items(things, REGIONS, region_geo, seen, "2026-08-31")
    check("[공매] 이미 본 물건은 NEW 아님", items2[0]["isNew"], False)
    check("[공매] 최초 관측일 유지", items2[0]["firstSeen"], "2026-08-30")

    summary = transform.build_auction_summary(items)
    check("[공매] 요약 건수", summary["count"], 1)
    check("[공매] 평균 최저가율", summary["avgBidRate"], 51.0)


def test_shared() -> None:
    check("롤링 3개월 경계(연도 넘김)", rolling_months(date(2026, 1, 15)), ["202511", "202512", "202601"])
    check("평단가 계산", transform.price_per_pyeong(350000, 84.98), round(350000 / (84.98 / 3.3058), 1))
    check("중위값 짝수개", transform.median([1, 3, 5, 9]), 4)
    check("면적 구간 - 소형", transform.bucket_label(30.0), "10평 미만")
    check("면적 구간 - 대형", transform.bucket_label(1200.0), "300평 이상")
    check("주소->시군구 매칭", region_by_address(REGIONS, "서울 강남구 역삼동 1").name, "강남구")
    check("주소->시군구 미매칭", region_by_address(REGIONS, "부산광역시 해운대구 우동"), None)


def main() -> int:
    for fn in (test_apt, test_commercial, test_land, test_auction, test_shared):
        fn()
    if failures:
        print(f"FAIL ({len(failures)}건)")
        for f in failures:
            print("  -", f)
        return 1
    print("OK - 모든 단언 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
