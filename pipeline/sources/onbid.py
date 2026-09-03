"""온비드(한국자산관리공사) 공매 물건 — 경매·공매 탭 Phase 1 (PRD 3.2-D).

법원경매는 무료 벌크 API 가 없어 이 단계에서는 다루지 않는다. 여기서 오는 것은
전부 '공매' 물건이며, UI 도 그렇게 표기한다.

2026년 1월 온비드 API 가 세대교체됐다. 구세대 캠코공매물건 조회서비스
(KamcoPblsalThingInquireSvc)는 공공데이터포털에서 폐지됐고, 여기서는 차세대
'부동산 물건목록 조회서비스'(data.go.kr ID 15157207)를 쓴다.
- 필수 검색 조건이 재산유형코드(prptDivCd)·수의계약가능여부(pvctTrgtYn)라서
  재산유형 × Y/N 조합을 순회해 전국 물건을 다 받는다. 건수가 적어
  전국 1파일(auction/onbid.json)로 낸다.
- 지번 주소를 통째로 주지 않는 대신 지번PNU(19자리)를 주므로 거기서 지번을 복원한다.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .. import config
from .common import as_float, as_int, get_with_retry, text_of

ENDPOINT = "https://apis.data.go.kr/B010003/OnbidRlstListSrvc2/getRlstCltrList2"
# 부동산 공매에 등장하는 재산유형 전부. 0004(불용품)는 동산이라 제외.
PRPT_DIV_CDS = ("0002", "0003", "0005", "0006", "0007", "0008", "0010", "0011", "0013")
NUM_OF_ROWS = 200
MAX_PAGES = 40


class OnbidError(RuntimeError):
    pass


# 차세대 온비드는 camelCase 필드명을 쓴다. 스펙 개편 대비로 별칭 구조는 유지한다.
F = {
    "mgmt_no": ("cltrMngNo",),
    "cdtn_no": ("pbctCdtnNo",),
    "name": ("onbidCltrNm",),
    "cat_l": ("cltrUsgLclsCtgrNm",),
    "cat_m": ("cltrUsgMclsCtgrNm",),
    "cat_s": ("cltrUsgSclsCtgrNm",),
    "sido": ("lctnSdnm",),
    "sgg": ("lctnSggnm",),
    "emd": ("lctnEmdNm",),
    "pnu": ("ltnoPnu",),
    "min_bid": ("lowstBidPrcIndctCont",),  # 숫자 또는 '비공개'
    "appraisal": ("apslEvlAmt",),
    "fee_rate": ("feeRate",),
    "begin": ("cltrBidBgngDt",),
    "close": ("cltrBidEndDt",),
    "status": ("pbctStatNm",),
    "disposal": ("dspsMthodNm",),
    "bid_method": ("bidMthodNm",),
    "institution": ("orgNm", "rqstOrgNm"),
    "fail_count": ("usbdNft",),
    "prpt_nm": ("prptDivNm",),
    "thumb": ("thnlImgUrlAdr",),
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


def _jibun_from_pnu(pnu: str) -> str:
    """지번PNU(19자리: 법정동10 + 산1 + 본번4 + 부번4) -> '725-10' / '산12' 형태."""
    if len(pnu) != 19 or not pnu.isdigit():
        return ""
    bon, bu = int(pnu[11:15]), int(pnu[15:19])
    if bon == 0:
        return ""
    san = "산" if pnu[10] == "2" else ""
    return f"{san}{bon}-{bu}" if bu else f"{san}{bon}"


def parse(xml_text: str) -> list[AuctionThing]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise OnbidError(f"XML 파싱 실패: {exc}: {xml_text[:200]}") from exc

    # 게이트웨이 오류(cmmMsgHeader)는 resultCode 없이 온다.
    err = root.find(".//errMsg")
    if err is not None and err.text:
        auth = root.find(".//returnAuthMsg")
        raise OnbidError(
            f"게이트웨이 오류: {err.text.strip()} "
            f"{(auth.text or '').strip() if auth is not None and auth.text else ''}"
        )

    code = root.find(".//resultCode")
    if code is not None and code.text and code.text.strip() not in ("00", "000", "03"):
        # 03(NODATA_ERROR)은 해당 재산유형×수의계약 조합에 물건이 없다는 뜻 — 정상 빈 응답.
        msg = root.find(".//resultMsg")
        raise OnbidError(
            f"온비드 API 오류 resultCode={code.text.strip()} "
            f"msg={(msg.text or '').strip() if msg is not None and msg.text else ''}"
        )

    out: list[AuctionThing] = []
    for item in root.iter("item"):
        name = text_of(item, F["name"])
        sido = text_of(item, F["sido"])
        sgg = text_of(item, F["sgg"])
        if not name or not (sido or sgg):
            continue
        address = " ".join(
            filter(None, (sido, sgg, text_of(item, F["emd"]), _jibun_from_pnu(text_of(item, F["pnu"]))))
        )
        # 물건관리번호+공매조건번호가 물건 1건(공매 조건 단위)을 유일하게 식별한다.
        key = "-".join(filter(None, (text_of(item, F["mgmt_no"]), text_of(item, F["cdtn_no"]))))
        if not key:
            continue
        category = " / ".join(
            filter(None, (text_of(item, F["cat_l"]), text_of(item, F["cat_m"]), text_of(item, F["cat_s"])))
        )
        out.append(
            AuctionThing(
                key=key,
                name=name,
                category=category,
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
                    "feeRate": as_float(text_of(item, F["fee_rate"])),
                    "mgmtNo": text_of(item, F["mgmt_no"]),
                    "cdtnNo": text_of(item, F["cdtn_no"]),
                    "prptDivNm": text_of(item, F["prpt_nm"]),
                    "thumbnail": text_of(item, F["thumb"]),
                },
            )
        )
    return out


def fetch_all(session) -> list[AuctionThing]:
    if not config.ONBID_SERVICE_KEY:
        raise OnbidError("ONBID_SERVICE_KEY 가 비어 있다. --mock 으로 실행하거나 키를 설정하라.")

    # 필수 검색 조건(재산유형 × 수의계약 Y/N)을 순회한다. 조합끼리는 겹치지 않지만,
    # 스펙이 바뀌어 겹치더라도 물건키 기준으로 안전하게 합친다.
    by_key: dict[str, AuctionThing] = {}
    for prpt_cd in PRPT_DIV_CDS:
        for pvct in ("Y", "N"):
            for page in range(1, MAX_PAGES + 1):
                body = get_with_retry(
                    session,
                    ENDPOINT,
                    {
                        "serviceKey": config.ONBID_SERVICE_KEY,
                        "prptDivCd": prpt_cd,
                        "pvctTrgtYn": pvct,
                        "numOfRows": NUM_OF_ROWS,
                        "pageNo": page,
                    },
                )
                rows = parse(body)
                for thing in rows:
                    by_key.setdefault(thing.key, thing)
                if len(rows) < NUM_OF_ROWS:
                    break
                time.sleep(0.2)
    return list(by_key.values())
