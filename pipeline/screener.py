"""수익 기회 스크리너 (급매 신호 + 공매 수익 랭킹).

디스크의 지역 파일 전체를 입력으로 screener.json 을 만든다 — rebuild_outputs 와
같은 원리로, 권역 분할 실행과 무관하게 매일 assemble 시점에 전량 재계산된다.

산식(리포트 '수익 기회 스크리너' 2026-09-06 과 동일):
  점수 = 100 × P(할인) × L(동네 유동성) × R(리스크 보정)
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import date

from . import config

# 급매 판정 파라미터. 아파트는 같은 면적대끼리 비교(정밀), 상가·토지는 물건이
# 이질적이라 단가(면적당 가격) 기준 + 더 보수적인 임계값을 쓴다.
URGENT_PARAMS = {
    "apt": {"drop": -12, "min_sample": 4, "label": "아파트"},
    "commercial": {"drop": -35, "min_sample": 5, "label": "상가"},
    "land": {"drop": -40, "min_sample": 6, "label": "토지"},
}
EXTREME_DROP_PCT = -40  # 직거래·증여성 이전 의심 구간 (아파트 기준)

CAT2KIND = {
    "주거용건물": "apt",
    "상가용및업무용건물": "commercial",
    "용도복합용건물": "commercial",
    "토지": "land",
}
KIND_WEIGHT = {"주거용건물": 1.05, "상가용및업무용건물": 0.95, "용도복합용건물": 0.9, "토지": 0.85}


def _base_name(name: str) -> str:
    """'… 제3층 제301호' 같은 호수 표기를 떼어 같은 건물을 묶는다."""
    return re.split(r" 제\d| 제[가-힣]?\d|\(", name)[0].strip()


def _liquidity_index(out_dir):
    liq: dict[tuple, dict] = defaultdict(lambda: {"count": 0, "amounts": []})
    for kind in ("apt", "commercial", "land"):
        for p in (out_dir / kind).glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            for it in d["items"]:
                k = (d["code"], it.get("umd", ""), kind)
                liq[k]["count"] += it.get("dealCount", 0)
                if it.get("medianAmount"):
                    liq[k]["amounts"].append(it["medianAmount"])
    return liq


def _row(kind, d, it, deal, ref_amount, drop, sample_n, note=None) -> dict:
    tags = []
    if kind == "apt" and (deal.get("floor") or 99) <= 2:
        tags.append("저층")
    if kind == "apt" and drop <= EXTREME_DROP_PCT:
        tags.append("직거래·특수거래 의심")
    if deal.get("share"):
        tags.append(f"{deal['share']} 거래")
    if note:
        tags.append(note)
    if sample_n < 6:
        tags.append(f"표본 {sample_n}건")
    return {
        "kind": kind,
        "kindLabel": URGENT_PARAMS[kind]["label"],
        "region": d["name"],
        "umd": it["umd"],
        "complex": it["name"],
        "area": deal["area"],
        "amount": deal["amount"],
        "median": ref_amount,
        "drop": round(drop, 1),
        "dealtAt": f"{deal['ym'][:4]}.{deal['ym'][4:]}.{deal['day']:02d}",
        "floor": deal.get("floor"),
        "sampleN": sample_n,
        "lat": it["lat"],
        "lng": it["lng"],
        "tags": tags,
    }


def _urgent_sales(out_dir) -> list[dict]:
    rows: dict[tuple, dict] = {}

    # 아파트: 같은 단지·면적대 중위가와 직접 비교 (가장 정밀)
    prm = URGENT_PARAMS["apt"]
    for p in (out_dir / "apt").glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        for it in d["items"]:
            by_area = {str(a["label"]): a for a in it.get("areas", [])}
            for deal in it.get("deals", []):
                a = by_area.get(str(deal["area"]))
                if not a or a["count"] < prm["min_sample"] or a["medianAmount"] <= 0:
                    continue
                drop = (deal["amount"] - a["medianAmount"]) / a["medianAmount"] * 100
                if drop > prm["drop"]:
                    continue
                key = ("apt", d["code"], it["name"], deal["area"])
                cand = _row("apt", d, it, deal, a["medianAmount"], drop, a["count"])
                if key not in rows or cand["drop"] < rows[key]["drop"]:
                    rows[key] = cand

    # 상가·토지: 같은 물건(건물 / 법정동×지목) 안에서 단가(만원/㎡) 비교.
    # 물건이 이질적(층·위치·필지 조건)이라 임계값을 보수적으로 잡고 유의 태그를 단다.
    for kind, note in (("commercial", "층·위치 차이 가능성"), ("land", "필지 조건 차이 유의")):
        prm = URGENT_PARAMS[kind]
        for p in (out_dir / kind).glob("*.json"):
            d = json.loads(p.read_text(encoding="utf-8"))
            for it in d["items"]:
                # 도로·구거·하천 지목은 거래가 명목 이전인 경우가 대부분 — 기회가 아니다.
                if kind == "land" and it["name"].endswith(("도로", "구거", "하천", "제방", "묘지")):
                    continue
                units = [
                    (deal, deal["amount"] / deal["area"])
                    for deal in it.get("deals", [])
                    if deal.get("area") and deal["area"] > 0 and not deal.get("share")
                ]
                if len(units) < prm["min_sample"]:
                    continue
                med = sorted(u for _, u in units)[len(units) // 2]
                if med <= 0:
                    continue
                for deal, unit in units:
                    drop = (unit - med) / med * 100
                    if drop > prm["drop"]:
                        continue
                    # -85% 이하·소액은 명목 이전(증여·무상 등) 노이즈로 본다.
                    if drop <= -85 or deal["amount"] < 100:
                        continue
                    key = (kind, d["code"], it["name"], deal["ym"], deal["day"], deal["area"])
                    ref = round(med * deal["area"])
                    cand = _row(kind, d, it, deal, ref, drop, len(units), note)
                    if key not in rows or cand["drop"] < rows[key]["drop"]:
                        rows[key] = cand

    return sorted(rows.values(), key=lambda x: x["drop"])


def _score_auction(it: dict, liq, today: date) -> dict | None:
    if it["disposal"] != "매각" or it["bidRate"] is None:
        return None
    if not (5 <= it["bidRate"] <= 85):
        return None
    days = None
    if it["closeAt"]:
        try:
            days = (date.fromisoformat(it["closeAt"][:10]) - today).days
        except ValueError:
            pass
    if not ((days is not None and days >= 0) or "수의계약" in it["status"]):
        return None

    mid = it["category"].split(" / ")[1] if " / " in it["category"] else it["category"]
    lkey = (it["regionCode"], it["umd"], CAT2KIND.get(mid))
    entry = liq.get(lkey)
    ln = entry["count"] if entry else 0
    amounts = entry["amounts"] if entry else []

    tags: list[str] = []
    # 할인 한계효용 체감: 80% 이상 할인은 리스크 대비 실익이 안 늘어난다고 본다.
    p = (100 - max(it["bidRate"], 20)) / 100
    liquidity = min(1.0, math.log1p(ln) / math.log1p(20)) if ln else 0.25
    r = KIND_WEIGHT.get(mid, 0.8)
    if ln == 0:
        tags.append("동네 거래근거 없음")
    if it["failCount"] >= 10:
        r *= 0.35
        tags.append(f"유찰 {it['failCount']}회 — 장기 미매각(문제물건 가능성)")
    elif it["failCount"] >= 8:
        r *= 0.5
        tags.append(f"유찰 {it['failCount']}회 과다")
    elif it["failCount"] >= 5:
        r *= 0.8
        tags.append(f"유찰 {it['failCount']}회")
    elif it["failCount"] == 0:
        r *= 0.9  # 신건 — 아직 할인 검증 전
    if it["minBid"] < 300:
        r *= 0.8
        tags.append("소액 — 지분·자투리 의심")
    if amounts:
        med = sorted(amounts)[len(amounts) // 2]
        if it["appraisal"] > 0 and med > 0 and (it["appraisal"] / med > 8 or med / it["appraisal"] > 8):
            r *= 0.7
            tags.append("감정가-동네시세 괴리 큼")
    # 유찰로 '벌어진' 할인인지 검증 — 유찰 없이 극단 저가면 지분·특수물건 신호.
    anomaly = max(5, 100 - 10 * it["failCount"]) - it["bidRate"]
    if anomaly >= 45:
        r *= 0.3
        tags.append("이례적 저가 — 지분·특수물건 강력 의심")
    elif anomaly >= 25:
        r *= 0.5
        tags.append("이례적 저가 — 지분·특수물건 의심")
    if it["extra"].get("prptDivNm") == "압류재산":
        tags.append("압류재산 — 권리분석 필수")
    if "수의계약" in it["status"]:
        tags.append("수의계약 가능")
    if days is not None and 0 <= days <= 3:
        r *= 0.9
        tags.append("마감 3일 이내")

    return {
        "score": round(100 * p * liquidity * r, 1),
        "id": it["id"],
        "name": it["name"],
        "category": mid,
        "region": it["regionName"],
        "umd": it["umd"],
        "minBid": it["minBid"],
        "appraisal": it["appraisal"],
        "bidRate": it["bidRate"],
        "failCount": it["failCount"],
        "closeAt": it["closeAt"][:10] if it["closeAt"] else "",
        "days": days,
        "status": it["status"],
        "liquidity": ln,
        "tags": tags,
        "mgmtNo": it["extra"].get("mgmtNo", ""),
        "lat": it["lat"],
        "lng": it["lng"],
    }


def build_screener(today: date) -> tuple[dict | None, int]:
    """screener.json 생성. (요약 dict, 파일 크기) — 입력 부족 시 (None, 0)."""
    out_dir = config.OUT_DIR
    auction_path = out_dir / "auction" / "onbid.json"
    if not auction_path.exists() or not any((out_dir / "apt").glob("*.json")):
        return None, 0

    liq = _liquidity_index(out_dir)
    urgent = _urgent_sales(out_dir)

    auc = json.loads(auction_path.read_text(encoding="utf-8"))
    scored = [s for s in (_score_auction(i, liq, today) for i in auc["items"]) if s]
    scored.sort(key=lambda x: -x["score"])

    # 같은 건물의 여러 호실은 대표 1건 + 묶음 수로 표시
    grouped: dict[tuple, dict] = {}
    for s in scored:
        k = (s["region"], s["umd"], _base_name(s["name"]))
        if k in grouped:
            grouped[k]["bundle"] += 1
            grouped[k]["minBid"] = min(grouped[k]["minBid"], s["minBid"])
        else:
            grouped[k] = {**s, "bundle": 1}
    auction_top = sorted(grouped.values(), key=lambda x: -x["score"])[:50]

    by_kind: dict[str, int] = {}
    for r in urgent:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    payload = {
        "generatedAt": today.isoformat(),
        "urgentTotal": len(urgent),
        "urgentByKind": by_kind,
        "auctionEligible": len(scored),
        "urgent": urgent[:50],
        "auctionTop": auction_top,
        "method": "점수 = 100 × 할인(P) × 동네 유동성(L) × 리스크 보정(R)",
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    (out_dir / "screener.json").write_text(text, encoding="utf-8")
    size = len(text.encode("utf-8"))
    print(f"  스크리너: 급매 {len(urgent)}건 / 공매 적격 {len(scored)}건 / {size/1024:.1f} KB")
    return payload, size
