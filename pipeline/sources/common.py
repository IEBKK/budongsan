"""국토부 실거래가 API 3종(아파트/상업업무용/토지)의 공통 수집·파싱 계층.

세 API 는 엔드포인트와 필드명만 다르고 호출 규약(serviceKey/LAWD_CD/DEAL_YMD/
페이지네이션)과 응답 골격(response>body>items>item)이 같다. 공통부를 여기 모으고
각 소스 모듈은 '엔드포인트 + 필드 매핑'만 선언한다.

필드명은 API 개편에 따라 현행 camelCase 와 구버전 한글 태그가 섞여 나오므로
모든 필드를 별칭 목록으로 받는다.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Sequence

from .. import config

NUM_OF_ROWS = 1000
MAX_PAGES = 20
RETRIES = 3
THROTTLE_SEC = 0.2  # 공공 API 초당 호출 제한 여유


class MolitError(RuntimeError):
    pass


@dataclass(frozen=True)
class Trade:
    """실거래 1건. 유형별 고유 항목은 extra 에 담는다."""

    sgg_code: str
    umd: str
    jibun: str
    name: str
    build_year: int | None
    area: float          # 아파트=전용면적, 상가=건물면적, 토지=거래면적 (m2)
    floor: int | None
    amount: int          # 만원
    ym: str              # YYYYMM
    day: int
    road_name: str = ""
    extra: dict = field(default_factory=dict)


def text_of(item: ET.Element, aliases: Sequence[str]) -> str:
    for tag in aliases:
        el = item.find(tag)
        if el is not None and el.text is not None:
            return el.text.strip()
    return ""


def as_int(value: str) -> int | None:
    digits = "".join(ch for ch in value if ch.isdigit() or ch == "-")
    try:
        return int(digits)
    except ValueError:
        return None


def as_float(value: str) -> float | None:
    cleaned = value.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def check_result_code(root: ET.Element) -> None:
    el = root.find(".//resultCode")
    if el is not None and el.text and el.text.strip() not in ("00", "000"):
        msg = root.find(".//resultMsg")
        detail = (msg.text or "").strip() if msg is not None and msg.text else ""
        raise MolitError(f"API 오류 resultCode={el.text.strip()} msg={detail}")


def parse_root(xml_text: str) -> ET.Element:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        # 인증 실패·쿼터 초과 시 XML 이 아닌 HTML/평문이 돌아오는 경우가 있다.
        raise MolitError(f"XML 파싱 실패: {exc}: {xml_text[:200]}") from exc
    check_result_code(root)
    return root


def total_count(xml_text: str) -> int:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return 0
    el = root.find(".//totalCount")
    return int(el.text.strip()) if el is not None and el.text else 0


def is_cancelled(item: ET.Element, aliases: Sequence[str]) -> bool:
    """해제(취소)된 거래는 집계에서 뺀다."""
    return text_of(item, aliases) in ("O", "o", "Y")


def fetch_month(session, endpoint: str, sgg_code: str, ym: str, parser) -> list[Trade]:
    """한 시군구·한 달치를 전 페이지 수집한다. parser(xml, sgg) -> list[Trade]"""
    if not config.MOLIT_SERVICE_KEY:
        raise MolitError("MOLIT_SERVICE_KEY 가 비어 있다. --mock 으로 실행하거나 키를 설정하라.")

    collected: list[Trade] = []
    for page in range(1, MAX_PAGES + 1):
        body = get_with_retry(
            session,
            endpoint,
            {
                "serviceKey": config.MOLIT_SERVICE_KEY,
                "LAWD_CD": sgg_code,
                "DEAL_YMD": ym,
                "pageNo": page,
                "numOfRows": NUM_OF_ROWS,
            },
        )
        rows = parser(body, sgg_code)
        collected.extend(rows)
        if page * NUM_OF_ROWS >= total_count(body) or not rows:
            break
        time.sleep(THROTTLE_SEC)
    return collected


def redact_keys(message: str) -> str:
    """예외 메시지에 인증키가 포함된 URL 이 들어올 수 있다(HTTPError 등).
    이 메시지는 공개 Actions 로그와 meta.json failedRegions 로 흘러가므로 반드시 가린다."""
    from urllib.parse import quote

    for key in (config.MOLIT_SERVICE_KEY, config.ONBID_SERVICE_KEY):
        if key:
            for variant in (key, quote(key, safe=""), quote(key)):
                message = message.replace(variant, "***")
    return message


def get_with_retry(session, endpoint: str, params: dict) -> str:
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            resp = session.get(endpoint, params=params, timeout=config.REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:  # noqa: BLE001 - 네트워크/HTTP 모두 재시도 대상
            last = exc
            time.sleep(1.5 * (attempt + 1))
    # HTTP 오류의 상태 코드만으론 원인을 알 수 없다(403 이 키 미반영·미신청·쿼터 초과 전부에 쓰인다).
    # 게이트웨이가 본문에 넣어 주는 오류 XML 을 함께 남긴다.
    detail = ""
    resp = getattr(last, "response", None)
    if resp is not None and resp.text:
        detail = " | 응답: " + " ".join(resp.text[:300].split())
    raise MolitError(redact_keys(f"요청 실패 (재시도 {RETRIES}회): {last}{detail}"))
