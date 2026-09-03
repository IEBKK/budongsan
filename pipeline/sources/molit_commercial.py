"""국토교통부 상업업무용 부동산 실거래가 (상가·오피스).

아파트와 달리 건물명이 비어 오는 경우가 많아, 표시명은
'건물주용도 + 지번' 으로 합성한다.
"""
from __future__ import annotations

from .common import (
    Trade,
    as_float,
    as_int,
    fetch_month as _fetch_month,
    is_cancelled,
    parse_root,
    text_of,
)

ENDPOINT = (
    "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade"
)

F = {
    "amount": ("dealAmount", "거래금액"),
    "year": ("dealYear", "년"),
    "month": ("dealMonth", "월"),
    "day": ("dealDay", "일"),
    "name": ("bldgNm", "건물명"),
    "building_area": ("buildingAr", "건물면적"),
    "plottage_area": ("plottageAr", "대지면적"),
    "floor": ("floor", "층"),
    "build_year": ("buildYear", "건축년도"),
    "jibun": ("jibun", "지번"),
    "umd": ("umdNm", "법정동"),
    "sgg": ("sggCd", "지역코드"),
    "road": ("roadNm", "도로명"),
    "use": ("buildingUse", "건물주용도"),
    "building_type": ("buildingType", "유형"),
    "land_use": ("landUse", "용도지역"),
    "cancelled": ("cdealType", "해제여부"),
}


def parse(xml_text: str, fallback_sgg: str = "") -> list[Trade]:
    root = parse_root(xml_text)
    out: list[Trade] = []
    for item in root.iter("item"):
        if is_cancelled(item, F["cancelled"]):
            continue
        amount = as_int(text_of(item, F["amount"]))
        area = as_float(text_of(item, F["building_area"]))
        year = as_int(text_of(item, F["year"]))
        month = as_int(text_of(item, F["month"]))
        if amount is None or area is None or not area or not year or not month:
            continue
        umd = text_of(item, F["umd"])
        jibun = text_of(item, F["jibun"])
        use = text_of(item, F["use"]) or "상업업무용"
        name = text_of(item, F["name"]) or f"{use} {jibun}".strip()
        out.append(
            Trade(
                sgg_code=text_of(item, F["sgg"]) or fallback_sgg,
                umd=umd,
                jibun=jibun,
                name=name,
                build_year=as_int(text_of(item, F["build_year"])),
                area=area,
                floor=as_int(text_of(item, F["floor"])),
                amount=amount,
                ym=f"{year:04d}{month:02d}",
                day=as_int(text_of(item, F["day"])) or 1,
                road_name=text_of(item, F["road"]),
                extra={
                    "use": use,
                    "buildingType": text_of(item, F["building_type"]),
                    "landUse": text_of(item, F["land_use"]),
                    "plottageAr": as_float(text_of(item, F["plottage_area"])),
                },
            )
        )
    return out


def fetch_month(session, sgg_code: str, ym: str) -> list[Trade]:
    return _fetch_month(session, ENDPOINT, sgg_code, ym, parse)
