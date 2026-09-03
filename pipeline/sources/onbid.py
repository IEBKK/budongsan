"""온비드(한국자산관리공사) 공매 물건 — 경매·공매 탭 Phase 1 (PRD 3.2-D).

법원경매는 무료 벌크 API 가 없어 이 단계에서는 다루지 않는다. 여기서 오는 것은
전부 '공매' 물건이며, UI 도 그렇게 표기한다.

시군구 단위 호출인 실거래가 API 와 달리 전국을 한 번에 페이지네이션으로 받는다.
건수가 적어 전국 1파일(auction/onbid.json)로 낸다.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .. import config
from .common import as_float, as_int, get_with_retry, text_of

ENDPOINT = (
    "http://openapi.onbid.co.kr/openapi/services/KamcoPblsalThingInquireSvc/getKamcoPbctCltrList"
)
NUM_OF_ROWS = 500
MAX_PAGES = 40


class OnbidError(RuntimeError):
    pass


# 온비드는 대문자 스네이크 필드명을 쓴다. 운영 중 스펙이 바뀔 때를 대비해 별칭을 둔다.
F = {
    "plan_no": ("PLNM_NO",),
    "cltr_no": ("CLTR_NO",),
    "hstr_no": ("CLTR_HSTR_NO",),
    "mgmt_no": ("BID_MNMT_NO", "CLTR_MNMT_NO"),
    "name": ("CLTR_NM", "GOODS_NM"),
    "category": ("CTGR_FULL_NM",),
    "address": ("LDNM_ADRS", "NMRD_ADRS"),
    "road_address": ("NMRD_ADRS",),
    "min_bid": ("MIN_BID_PRC",),
    "appraisal": ("APSL_ASES_AVG_AMT",),
    "fee_rate": ("FEE_RATE",),
    "begin": ("PBCT_BEGN_DTM",),
    "close": ("PBCT_CLS_DTM",),
    "status": ("PBCT_CLTR_STAT_NM",),
    "disposal": ("DPSL_MTD_NM",),
    "bid_method": ("BID_MTD_NM",),
    "institution": ("MANE_INST_NM",),
    "fail_count": ("USCBD_CNT",),
}


@dataclass(frozen=True)
class AuctionThing:
    key: str
    name: str
    category: str
    address: str
    min_bid: int          # 원
    appraisal: int        # 원
    fail_count: int
    begin_at: str         # ISO8601 or ''
    close_at: str
    status: str
    disposal: str
    bid_method: str
    institution: str
    extra: dict = field(default_factory=dict)

    @property
    def bid_rate(self) -> float | None:
        """최저입찰가 / 감정가 — 유찰이 쌓일수록 낮아진다 (추천 엔진의 핵심 시그널)."""
        if self.appraisal > 0 and self.min_bid > 0:
            return round(self.min_bid / self.appraisal * 100, 1)
        return None


def _dtm(raw: str) -> str:
    """'20260830103000' 또는 '2026-08-30 10:30:00' → ISO8601."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 8:
        return ""
    d = f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(digits) >= 12:
        d += f"T{digits[8:10]}:{digits[10:12]}"
    return d


def parse(xml_text: str) -> list[AuctionThing]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise OnbidError(f"XML 파싱 실패: {exc}: {xml_text[:200]}") from exc

    code = root.find(".//resultCode")
    if code is not None and code.text and code.text.strip() not in ("00", "000"):
        msg = root.find(".//resultMsg")
        raise OnbidError(
            f"온비드 API 오류 resultCode={code.text.strip()} "
            f"msg={(msg.text or '').strip() if msg is not None and msg.text else ''}"
        )

    out: list[AuctionThing] = []
    for item in root.iter("item"):
        name = text_of(item, F["name"])
        address = text_of(item, F["address"])
        if not name or not address:
            continue
        # 공고번호+물건번호+이력번호가 물건 1건을 유일하게 식별한다.
        key = "-".join(
            filter(None, (text_of(item, F["plan_no"]), text_of(item, F["cltr_no"]), text_of(item, F["hstr_no"])))
        ) or text_of(item, F["mgmt_no"])
        if not key:
            continue
        out.append(
            AuctionThing(
                key=key,
                name=name,
                category=text_of(item, F["category"]),
                address=address,
                min_bid=as_int(text_of(item, F["min_bid"])) or 0,
                appraisal=as_int(text_of(item, F["appraisal"])) or 0,
                fail_count=as_int(text_of(item, F["fail_count"])) or 0,
                begin_at=_dtm(text_of(item, F["begin"])),
                close_at=_dtm(text_of(item, F["close"])),
                status=text_of(item, F["status"]),
                disposal=text_of(item, F["disposal"]),
                bid_method=text_of(item, F["bid_method"]),
                institution=text_of(item, F["institution"]),
                extra={
                    "roadAddress": text_of(item, F["road_address"]),
                    "feeRate": as_float(text_of(item, F["fee_rate"])),
                    "mgmtNo": text_of(item, F["mgmt_no"]),
                },
            )
        )
    return out


def fetch_all(session) -> list[AuctionThing]:
    if not config.ONBID_SERVICE_KEY:
        raise OnbidError("ONBID_SERVICE_KEY 가 비어 있다. --mock 으로 실행하거나 키를 설정하라.")

    collected: list[AuctionThing] = []
    for page in range(1, MAX_PAGES + 1):
        body = get_with_retry(
            session,
            ENDPOINT,
            {
                "serviceKey": config.ONBID_SERVICE_KEY,
                "numOfRows": NUM_OF_ROWS,
                "pageNo": page,
            },
        )
        rows = parse(body)
        collected.extend(rows)
        if len(rows) < NUM_OF_ROWS:
            break
        time.sleep(0.2)
    return collected
