"""국토교통부 토지 실거래가.

주의: 이 API 는 지번을 제공하지 않는다(법정동까지만). 따라서 물건 단위 식별이
불가능하고, 집계·지도 표시 모두 '법정동 × 지목' 단위가 최소 해상도다.
층·건축년도 개념도 없다.
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
    "https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade"
)

F = {
    "amount": ("dealAmount", "거래금액"),
    "year": ("dealYear", "년"),
    "month": ("dealMonth", "월"),
    "day": ("dealDay", "일"),
    "area": ("dealArea", "거래면적"),
    "jimok": ("jimok", "지목"),
    "land_use": ("landUse", "용도지역"),
    "umd": ("umdNm", "법정동"),
    "sgg": ("sggCd", "지역코드"),
    "share": ("shareDealingType", "지분거래구분"),
    "cancelled": ("cdealType", "해제여부"),
}


def parse(xml_text: str, fallback_sgg: str = "") -> list[Trade]:
    root = parse_root(xml_text)
    out: list[Trade] = []
    for item in root.iter("item"):
        if is_cancelled(item, F["cancelled"]):
            continue
        amount = as_int(text_of(item, F["amount"]))
        area = as_float(text_of(item, F["area"]))
        year = as_int(text_of(item, F["year"]))
        month = as_int(text_of(item, F["month"]))
        if amount is None or area is None or not area or not year or not month:
            continue
        umd = text_of(item, F["umd"])
        jimok = text_of(item, F["jimok"]) or "기타"
        out.append(
            Trade(
                sgg_code=text_of(item, F["sgg"]) or fallback_sgg,
                umd=umd,
                jibun="",  # 토지 API 는 지번 미제공
                name=f"{umd} {jimok}".strip(),
                build_year=None,
                area=area,
                floor=None,
                amount=amount,
                ym=f"{year:04d}{month:02d}",
                day=as_int(text_of(item, F["day"])) or 1,
                extra={
                    "jimok": jimok,
                    "landUse": text_of(item, F["land_use"]),
                    "shareType": text_of(item, F["share"]),
                },
            )
        )
    return out


def fetch_month(session, sgg_code: str, ym: str) -> list[Trade]:
    return _fetch_month(session, ENDPOINT, sgg_code, ym, parse)
