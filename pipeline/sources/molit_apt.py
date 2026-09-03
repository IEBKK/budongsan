"""국토교통부 아파트 매매 실거래가."""
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
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
)

# 현행 camelCase 우선, 구버전 한글 태그 후순위
F = {
    "amount": ("dealAmount", "거래금액"),
    "year": ("dealYear", "년"),
    "month": ("dealMonth", "월"),
    "day": ("dealDay", "일"),
    "name": ("aptNm", "아파트", "apt"),
    "area": ("excluUseAr", "전용면적"),
    "floor": ("floor", "층"),
    "build_year": ("buildYear", "건축년도"),
    "jibun": ("jibun", "지번"),
    "umd": ("umdNm", "법정동"),
    "sgg": ("sggCd", "지역코드"),
    "road": ("roadNm", "도로명"),
    "cancelled": ("cdealType", "해제여부"),
    "dong": ("aptDong", "동"),
}


def parse(xml_text: str, fallback_sgg: str = "") -> list[Trade]:
    root = parse_root(xml_text)
    out: list[Trade] = []
    for item in root.iter("item"):
        if is_cancelled(item, F["cancelled"]):
            continue
        amount = as_int(text_of(item, F["amount"]))
        area = as_float(text_of(item, F["area"]))
        name = text_of(item, F["name"])
        year = as_int(text_of(item, F["year"]))
        month = as_int(text_of(item, F["month"]))
        if amount is None or area is None or not name or not year or not month:
            continue
        out.append(
            Trade(
                sgg_code=text_of(item, F["sgg"]) or fallback_sgg,
                umd=text_of(item, F["umd"]),
                jibun=text_of(item, F["jibun"]),
                name=name,
                build_year=as_int(text_of(item, F["build_year"])),
                area=area,
                floor=as_int(text_of(item, F["floor"])),
                amount=amount,
                ym=f"{year:04d}{month:02d}",
                day=as_int(text_of(item, F["day"])) or 1,
                road_name=text_of(item, F["road"]),
                extra={"dong": text_of(item, F["dong"])},
            )
        )
    return out


def fetch_month(session, sgg_code: str, ym: str) -> list[Trade]:
    return _fetch_month(session, ENDPOINT, sgg_code, ym, parse)
