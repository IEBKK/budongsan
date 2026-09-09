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


def _row(kind, d, it, deal, ref_amount, drop, sample_n, note=None, band=None) -> dict:
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
        # 오늘의 추천 상세 분석용 근거 (면적대/물건 내 가격 분포 등)
        "band": band or {},
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
                band = {
                    "min": a["minAmount"], "median": a["medianAmount"], "max": a["maxAmount"],
                    "pricePerPyeong": a.get("pricePerPyeong"),
                    "complexDeals": it.get("dealCount", 0), "lastYm": it.get("lastYm", ""),
                    "buildYear": it.get("buildYear"),
                }
                cand = _row("apt", d, it, deal, a["medianAmount"], drop, a["count"], band=band)
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
                    us = sorted(u for _, u in units)
                    band = {
                        "unitMin": round(us[0], 1), "unitMedian": round(med, 1),
                        "unitMax": round(us[-1], 1), "unit": round(deal["amount"]/deal["area"], 1),
                        "complexDeals": it.get("dealCount", 0), "lastYm": it.get("lastYm", ""),
                    }
                    cand = _row(kind, d, it, deal, ref, drop, len(units), note, band=band)
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
        "factors": {"P": round(p, 2), "L": round(liquidity, 2), "R": round(r, 2)},
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


# 오늘의 추천 상세 — 유형별 '입찰·매수 전 확인' 체크리스트
CHECKLISTS = {
    "apt": [
        "등기부등본 — 근저당·가압류·신탁 여부",
        "직거래(중개사 미개입) 신고인지 — 특수관계 거래면 시세 신호 아님",
        "층·향·수리 상태 현장 확인 (같은 면적대라도 조건차 큼)",
        "현재 호가와 비교 — 신고가는 1~2개월 전 계약분",
    ],
    "commercial": [
        "임차 현황 — 보증금·월세 승계 조건, 공실 여부",
        "층별 효용 차이 — 저층·고층 단가는 원래 크게 다름",
        "건물 용도·용도변경 제한 확인",
        "관리비·공용부 상태, 상권 공실률",
    ],
    "land": [
        "용도지역·개발행위 제한 (토지이용계획확인원)",
        "도로 접면 여부 — 맹지면 가치 급감",
        "지분·필지 분할 거래인지 확인",
        "공시지가·인근 경매 낙찰가와 교차 확인",
    ],
    "auction": [
        "온비드 원문 공고 — 권리관계(임차인·유치권·법정지상권)",
        "지분 매각 여부 — 감정가는 전체 기준일 수 있음",
        "명도 책임과 점유 현황",
        "입찰보증금·잔금 일정, 세금 체납 인수 여부",
        "현장 확인 — 사진과 실물 상태 차이",
    ],
}

# ── 오늘의 추천 상세 — 수익 시나리오·리스크 매트릭스 ──────────────────
# 세제·비용 가정은 1주택 개인·전액 자기자본 기준의 근사값이다. 정확한 세액은
# 물건·매수인 조건에 따라 달라지므로 화면에는 항상 '세전·근사' 단서를 단다.

def _eok(man: float) -> str:
    return f"{man/10000:.2f}억" if abs(man) >= 10000 else f"{man:,.0f}만"


def _acq_pct(kind: str, price: float) -> float:
    """취득세+지방교육세(+농특) 근사율(%). 주택은 가액 구간별, 상가·토지는 4.6% 고정."""
    if kind == "apt":
        if price <= 60000:
            return 1.1
        if price <= 90000:
            return 2.2
        return 3.5
    return 4.6


# 단기 양도세 안내 (지방소득세 별도) — 시나리오가 세전인 이유를 설명한다.
CGT_NOTE = {
    "apt": "양도세(주택): 1년 미만 70%·2년 미만 60% — 단기 전매 차익은 대부분 과세로 상쇄. 실거주 비과세 요건 또는 2년+ 보유 설계가 현실적.",
    "commercial": "양도세(상가): 1년 미만 50%·2년 미만 40%, 이후 기본세율 — 세후 수익은 보유기간 설계에 좌우.",
    "land": "양도세(토지): 1년 미만 50%·2년 미만 40% + 비사업용 토지는 기본세율+10%p 중과 — 세후 수익은 보유기간·사업용 여부에 좌우.",
}


def _scenario_row(label: str, sell_label: str, buy: float, sell: float, fixed_cost: float) -> list[str]:
    """한 시나리오의 (라벨, 매도 가정, 세전 차익, 투입 대비 수익률) 행."""
    net = sell - buy - fixed_cost - sell * 0.004  # 매도 중개보수 ~0.4%
    invested = buy + fixed_cost
    roi = net / invested * 100 if invested > 0 else 0
    sign = "−" if net < 0 else "+"
    return [label, sell_label, f"{sign}{_eok(abs(net))}", f"{roi:+.1f}%"]


def _profit_urgent(u: dict) -> dict:
    buy, med, kind = u["amount"], u["median"], u["kind"]
    pct = _acq_pct(kind, buy)
    acq = buy * pct / 100
    broker_in = buy * 0.004
    fixed = acq + broker_in
    scenarios = [
        _scenario_row("시세 회복 매도", f"시세 기준 {_eok(med)}", buy, med, fixed),
        _scenario_row("보수적 매도 (시세 −10%)", _eok(med * 0.9), buy, med * 0.9, fixed),
        _scenario_row("급처분 (시세 −20%)", _eok(med * 0.8), buy, med * 0.8, fixed),
    ]
    assumptions = [
        "이 가격대로 매물을 확보할 수 있을 때의 시나리오 — 신고가는 1~2개월 전 계약분이라 현재 호가와 다를 수 있음.",
        f"취득 부대비용 {pct}% + 중개보수(왕복 ~0.8%) 반영, 전액 자기자본·보유/금융비용 미포함.",
        CGT_NOTE[kind],
    ]
    if (kind == "apt" and u["drop"] <= EXTREME_DROP_PCT) or (kind != "apt" and u["drop"] <= -60):
        assumptions.insert(0, "⚠ 할인 폭이 특수거래·조건차 의심 구간 — 아래 리스크가 해소되기 전에는 시나리오 자체가 무의미함.")
    return {
        "scenarios": scenarios,
        "costs": [
            ("매입가 가정", _eok(buy)),
            (f"취득세 등 (~{pct}%)", _eok(acq)),
            ("매수 중개보수 (~0.4%)", _eok(broker_in)),
            ("총 투입 (세전)", _eok(buy + fixed)),
        ],
        "assumptions": assumptions,
    }


def _risks_urgent(u: dict, this_year: int) -> list[list[str]]:
    kind, drop, n = u["kind"], u["drop"], u["sampleN"]
    band = u.get("band", {})
    risks: list[list[str]] = []

    if kind == "apt":
        if drop <= EXTREME_DROP_PCT:
            risks.append(["시세 신호 진정성", "높음", "직거래·증여 등 특수관계 이전 의심 구간 — 등기부와 신고 유형(직거래 여부) 확인 전에는 시세 신호로 볼 수 없음."])
        elif drop <= -25:
            risks.append(["시세 신호 진정성", "중간", "정상 급매 범위지만 하자(수리 상태·향·소송·임차 승계) 가능성을 병행 확인해야 함."])
        else:
            risks.append(["시세 신호 진정성", "낮음", "통상적 급매 폭 — 다만 저층·수리 미비 등 조건차는 현장에서 확인."])
    elif kind == "commercial":
        risks.append(["시세 신호 진정성", "높음" if drop <= -60 else "중간",
                      "같은 건물이라도 층·위치 효용 차이가 큰 단가 차이를 흔히 만듦 — 저층/고층·전면/후면 대비를 확인해야 진짜 할인인지 판별됨."])
    else:
        risks.append(["시세 신호 진정성", "높음" if drop <= -60 else "중간",
                      "필지 조건(맹지·경사·형상·지분) 차이일 가능성 — 토지이용계획확인원과 지적도로 검증 필요."])

    if n < 5:
        risks.append(["시세 기준 신뢰도", "높음", f"비교 표본이 최근 3개월 {n}건뿐 — 시세 기준 자체가 흔들릴 수 있음."])
    elif n < 8:
        risks.append(["시세 기준 신뢰도", "중간", f"비교 표본 {n}건 — 기준가는 참고치로, 현재 호가와 교차 확인."])
    else:
        risks.append(["시세 기준 신뢰도", "낮음", f"비교 표본 {n}건으로 기준가가 비교적 단단함."])

    deals = band.get("complexDeals", 0)
    if deals < 3:
        risks.append(["환금성", "높음", f"해당 물건 3개월 거래 {deals}건 — 되팔 때 매수자를 찾기 어려울 수 있음."])
    elif deals < 10:
        risks.append(["환금성", "중간", f"해당 물건 3개월 거래 {deals}건 — 급처분 시 추가 할인 각오."])
    else:
        risks.append(["환금성", "낮음", f"해당 물건 3개월 거래 {deals}건 — 거래가 꾸준한 편."])

    if kind == "apt" and band.get("buildYear") and this_year - band["buildYear"] >= 30:
        risks.append(["노후도", "중간", f"{band['buildYear']}년식({this_year - band['buildYear']}년차) — 수선·설비 교체 예산 필요. 재건축 기대는 지역별로 편차 큼."])
    if u["amount"] < 5000:
        risks.append(["절대 차익 규모", "중간", "초저가 물건 — 차익 절대액이 작아 거래비용·세금이 수익 대부분을 잠식할 수 있음."])
    return risks


def _profit_auction(s: dict, kind: str) -> dict:
    buy, appr = s["minBid"], s["appraisal"]
    pct = _acq_pct(kind, buy)
    buffer = appr * 0.015  # 명도·수리·미납관리비 예비비 ~1.5%
    fixed = buy * pct / 100 + buffer
    buy2 = buy * 1.05
    fixed2 = buy2 * pct / 100 + buffer
    scenarios = [
        _scenario_row("최저가 낙찰 → 감정가 90% 매도", _eok(appr * 0.9), buy, appr * 0.9, fixed),
        _scenario_row("최저가 낙찰 → 감정가 80% 매도", _eok(appr * 0.8), buy, appr * 0.8, fixed),
        _scenario_row("경합 +5% 낙찰 → 감정가 80% 매도", _eok(appr * 0.8), buy2, appr * 0.8, fixed2),
    ]
    assumptions = [
        f"취득 부대비용 ~{pct}% + 명도·수리·미납관리비 예비비(감정가의 1.5%) 반영, 세전·전액 자기자본 기준.",
        "공매는 대금 완납 시 소유권 취득 — 경락잔금대출 가능 여부와 잔금 일정을 입찰 전에 확인.",
        CGT_NOTE.get(kind, CGT_NOTE["commercial"]),
    ]
    if s["failCount"] >= 5:
        assumptions.insert(0, f"⚠ 감정가는 최초 공고 시점 평가액이고 유찰 {s['failCount']}회는 시장이 그 가격을 거부했다는 뜻 — 보수(80%) 시나리오 기준으로 판단 권장.")
    return {
        "scenarios": scenarios,
        "costs": [
            ("최저입찰가", _eok(buy)),
            ("입찰보증금 (최저가의 10%)", _eok(buy * 0.1)),
            (f"취득세 등 (~{pct}%)", _eok(buy * pct / 100)),
            ("명도·수리 예비비 (감정가 1.5%)", _eok(buffer)),
            ("총 투입 (세전)", _eok(buy + fixed)),
        ],
        "assumptions": assumptions,
    }


def _risks_auction(s: dict) -> list[list[str]]:
    risks: list[list[str]] = []
    if any("압류재산" in t for t in s["tags"]):
        risks.append(["권리관계", "높음", "압류재산 — 대항력 있는 임차인·당해세·체납 인수 범위를 권리분석으로 반드시 확정해야 함."])
    else:
        risks.append(["권리관계", "중간", "온비드 원문 공고의 권리신고 내역(임차인·유치권·법정지상권)을 확인하기 전에는 단정 불가."])

    fc = s["failCount"]
    if fc >= 8:
        risks.append(["유찰 이력", "높음", f"유찰 {fc}회 — 가격 문제를 넘어 물건 자체 하자(권리·명도·상태) 신호일 수 있음. 공고 원문에서 사유 추적 필수."])
    elif fc >= 5:
        risks.append(["유찰 이력", "중간", f"유찰 {fc}회 — 할인은 검증됐지만 왜 아무도 안 사갔는지 원문에서 확인할 것."])
    elif fc == 0:
        risks.append(["유찰 이력", "중간", "신건 — 아직 시장 검증 전이라 감정가 대비 할인의 적정성이 확인되지 않음."])
    else:
        risks.append(["유찰 이력", "낮음", f"유찰 {fc}회 — 회당 체감과 정합하는 범위."])

    if CAT2KIND.get(s["category"]) == "apt":
        risks.append(["명도", "높음", "주거용 — 점유자(임차인·전 소유자) 명도 책임은 매수인에게 있음. 명도비·소요기간(수개월)을 예산에 반영."])
    else:
        risks.append(["명도", "중간", "점유 현황에 따라 명도 협상·인도명령 비용 발생 가능 — 현장에서 점유자 확인."])

    if any("괴리" in t for t in s["tags"]):
        risks.append(["감정가 신뢰도", "높음", "감정가가 동네 시세와 크게 어긋남 — 감정가 기반 수익 시나리오를 그대로 믿으면 안 됨."])
    else:
        risks.append(["감정가 신뢰도", "중간", "감정 시점 이후 시장 변동이 반영되지 않음 — 인근 실거래가와 교차 확인."])

    ln = s["liquidity"]
    if ln >= 20:
        risks.append(["환금성", "낮음", f"같은 동네·자산군 3개월 거래 {ln}건 — 처분 근거가 충분함."])
    elif ln >= 8:
        risks.append(["환금성", "중간", f"같은 동네·자산군 3개월 거래 {ln}건 — 매도 호흡을 길게 잡을 것."])
    else:
        risks.append(["환금성", "높음", f"같은 동네·자산군 3개월 거래 {ln}건 — 낙찰 후 장기 보유를 각오해야 함."])

    if s["days"] is not None and s["days"] < 0 and "수의계약" in s["status"]:
        risks.append(["일정", "중간", f"입찰 공고 마감({s['closeAt']}) 경과 — 현재는 수의계약 단계. 온비드에서 진행 가능 여부를 즉시 확인해야 함."])
    elif s["days"] is not None and 0 <= s["days"] <= 3:
        risks.append(["일정", "중간", f"마감 D-{s['days']} — 권리분석·현장 확인 시간이 촉박함."])
    return risks


# ── 오늘의 코칭 — 추천 중 최우선 1건을 전문가 코치 톤으로 안내 ─────────
# 선정 기준: '높음' 리스크가 적은 순 → '중간' 리스크가 적은 순 → 검증 난이도가
# 낮은 자산 순(아파트 > 공매 > 상가 > 토지). 할인 폭이 커도 신호를 믿기 어려운
# 물건보다, 개인이 검증 절차만으로 접근 가능한 물건을 1픽으로 올린다.
KIND_PRIORITY = {"apt": 0, "auction": 1, "commercial": 2, "land": 3}


def _risk_counts(pick: dict) -> tuple[int, int]:
    rs = pick.get("analysis", {}).get("risks", [])
    return (sum(1 for r in rs if r[1] == "높음"), sum(1 for r in rs if r[1] == "중간"))


def _coach_urgent(pick: dict, u: dict) -> tuple[list[dict], list[list[str]]]:
    kind = u["kind"]
    amount, med = _eok(u["amount"]), _eok(u["median"])
    gap = _eok(u["median"] - u["amount"])
    basis = f"같은 단지 {u['area']}㎡ 면적대" if kind == "apt" else "같은 물건 내 단가"
    sc = pick["analysis"]["profit"]["scenarios"]
    total_in = dict(pick["analysis"]["profit"]["costs"]).get("총 투입 (세전)", amount)
    steps = [
        {"title": "이 물건, 한 줄로", "widget": "metrics", "body": [
            f"{u['region']} {u['umd']}의 {u['complex']}({u['area']}㎡). {basis} 시세가 {med}인데 {amount}에 신고된 거래가 포착됐습니다.",
            f"이 갭({abs(u['drop']):.0f}%, 차액 {gap})이 진짜라면 안전마진을 안고 시작하는 셈이고, 가짜라면(특수거래·조건차) 그냥 남의 일입니다. 오늘 코칭의 목표는 이 숫자가 진짜인지 순서대로 확인하는 것입니다.",
        ]},
        {"title": "자금 계획부터", "widget": "funding", "body": [
            f"이 가격대로 잡는다고 가정하면 세금·수수료까지 총 투입은 약 {total_in}입니다.",
            "대출을 쓰더라도 '급처분 시나리오에서도 버틸 수 있는 한도'까지만 쓰세요. 급매 투자는 싸게 사는 사람이 아니라, 싸게 사서 버틸 수 있는 사람이 이깁니다.",
        ], "point": "자기자본이 총 투입의 30%가 안 되면 이 물건은 패스하는 것이 원칙입니다. 최악 시나리오에서 버티지 못합니다."},
        {"title": "수익 시나리오 읽는 법", "widget": "scenarios", "body": [
            f"아래 표에서 의사결정 기준은 가운데 줄, '{sc[1][0]}'입니다 — 세전 {sc[1][2]}, 수익률 {sc[1][3]}. 시세 회복은 보너스로, 급처분은 방어선으로 읽으세요.",
            "보수 시나리오가 본인 목표수익률(통상 연 환산 두 자릿수)을 넘지 못하면 나머지 확인 절차를 진행할 이유가 없습니다.",
        ], "point": "세전 숫자에 취하지 마세요. 1년 내 전매면 양도세가 차익의 절반 이상을 가져갑니다 — 보유기간 계획이 곧 수익률입니다."},
        {"title": "리스크, 이 순서로 소거", "widget": "risks", "body": [
            "아래 등급 순서대로 하나씩 확인해 지워 나가세요. '높음'이 하나라도 해소되지 않으면 다음 단계로 넘어가지 않는 것이 원칙입니다.",
        ]},
        {"title": "실행 플랜", "widget": "plan", "body": [
            "확인은 돈이 들지 않습니다. 계약금이 나가기 전까지가 코칭 구간이고, 그 전에 아래 순서를 끝내세요.",
        ]},
        {"title": "출구 전략과 세금", "body": [
            CGT_NOTE[kind],
            "매수 전에 매도 목표가와 손절선을 숫자로 적어두세요. 목표가에 도달하면 미련 없이 파는 것 — 이 전략의 전부입니다.",
        ], "point": "출구가 그려지지 않는 물건은 아무리 싸도 사지 않습니다."},
    ]
    plan = [
        ["오늘", "등기부등본 열람(근저당·가압류·신탁) + 실거래 신고 유형(직거래 여부) 확인"],
        ["이번 주", "현장 방문 — 층·향·수리 상태 확인, 인근 중개사 2곳에서 현재 호가와 급매 사유 청취"],
        ["협상 단계", f"확인된 하자만큼만 깎는 원칙으로 {amount} 안팎 제시 — 시세 {med} 대비 근거를 갖고 협상"],
        ["계약 전", "잔금 일정·대출 실행 가능 여부 확정, 특약에 하자·임차 승계 조건 명시"],
    ]
    return steps, plan


def _coach_auction(pick: dict, s: dict) -> tuple[list[dict], list[list[str]]]:
    appr, min_bid = _eok(s["appraisal"]), _eok(s["minBid"])
    sc = pick["analysis"]["profit"]["scenarios"]
    costs = dict(pick["analysis"]["profit"]["costs"])
    total_in = costs.get("총 투입 (세전)", min_bid)
    deposit = costs.get("입찰보증금 (최저가의 10%)", "")
    negotiable = "수의계약" in s["status"]
    steps = [
        {"title": "이 물건, 한 줄로", "widget": "metrics", "body": [
            f"{s['region']} {s['umd']}의 공매 물건. 감정가 {appr}짜리를 최저 {min_bid}({s['bidRate']:.0f}%)부터 부를 수 있습니다.",
            f"유찰 {s['failCount']}회 — 시장이 {s['failCount']}번 거절했다는 뜻입니다. 그 이유를 찾아내는 것이 이번 코칭의 핵심이고, 이유가 '가격'뿐이라면 기회, '권리·명도'라면 초보자는 물러설 자리입니다."
            + (" 공고 마감은 지났지만 수의계약 단계라 아직 살 수 있습니다 — 첫 확인은 온비드 진행 여부입니다." if negotiable and (s["days"] or 0) < 0 else ""),
        ]},
        {"title": "자금 계획부터", "widget": "funding", "body": [
            f"입찰보증금 {deposit}이 먼저 나가고, 낙찰되면 정해진 기한 안에 잔금을 완납해야 소유권이 넘어옵니다. 총 투입은 약 {total_in}(최저가 기준, 세전).",
            "경락잔금대출이 되는 물건인지 입찰 '전에' 은행에 확인하세요. 잔금을 못 내면 보증금을 몰수당합니다 — 공매에서 가장 흔한 초보 사고입니다.",
        ], "point": "잔금 조달 계획 없이 입찰장에 들어가지 않습니다. 보증금 몰수는 연습비로는 너무 비쌉니다."},
        {"title": "수익 시나리오 읽는 법", "widget": "scenarios", "body": [
            f"감정가는 최초 공고 시점 평가액입니다. 유찰 {s['failCount']}회면 그 가격은 이미 시장에서 거부된 값 — 판단 기준은 보수 줄('{sc[1][0]}': 세전 {sc[1][2]}, {sc[1][3]})로 잡으세요.",
            "입찰가 상한도 여기서 나옵니다: 보수 시나리오가 목표수익률을 지키는 최대 가격까지만 쓰고, 경합이 붙어도 그 위로는 따라가지 않습니다.",
        ], "point": "낙찰이 목표가 아니라 수익이 목표입니다. 입찰가 상한을 넘겨 이기는 순간, 진 것입니다."},
        {"title": "리스크, 이 순서로 소거", "widget": "risks", "body": [
            "공매는 권리분석이 절반입니다. 아래 등급 순서대로 소거하되, '높음'이 해소되지 않으면 입찰하지 않는 것이 원칙입니다.",
        ]},
        {"title": "실행 플랜", "widget": "plan", "body": [
            "입찰 전까지가 코칭 구간입니다. 보증금이 나가기 전에 아래 순서를 끝내세요.",
        ]},
        {"title": "출구 전략과 세금", "body": [
            CGT_NOTE.get(CAT2KIND.get(s["category"], "commercial"), CGT_NOTE["commercial"]),
            "낙찰 후 명도까지의 기간(수개월)도 보유기간입니다. 매도 목표가와 최장 보유 한도를 미리 숫자로 적어두세요.",
        ], "point": "출구가 그려지지 않는 물건은 아무리 싸도 입찰하지 않습니다."},
    ]
    plan = [
        ["오늘", ("온비드에서 수의계약 진행 가능 여부 확인 + " if negotiable and (s["days"] or 0) < 0 else "")
         + "원문 공고 정독 — 권리신고 내역·임차 현황·지분 여부·유의사항"],
        ["이번 주", "현장 방문(점유자 확인) + 인근 실거래가로 감정가 검증"],
        ["입찰 전", "명도 시나리오·예산 확정, 경락잔금대출 가능 여부 은행 확인, 보증금 준비"],
        ["입찰가 산정", "보수 시나리오 기준 목표수익률을 지키는 최대 가격을 상한으로 — 상한 초과 경합은 포기"],
    ]
    return steps, plan


def _coach(picks: list[dict], raws: dict[str, dict], today: date) -> dict | None:
    if not picks:
        return None
    ranked = sorted(picks, key=lambda p: (*_risk_counts(p), KIND_PRIORITY.get(p["kind"], 9)))
    best = ranked[0]
    raw = raws.get(best["kind"])
    if raw is None:
        return None
    hi, mid = _risk_counts(best)
    if hi == 0:
        why = "'높음' 등급 리스크 없이, 검증 절차만으로 접근 가능한 후보라서입니다."
    else:
        why = "모든 후보에 '높음' 리스크가 있지만, 이 물건의 리스크는 서류·현장 확인으로 해소 가능한 구성이라서입니다."
    others = ", ".join(
        f"{p['kindLabel']}(높음 {_risk_counts(p)[0]}·중간 {_risk_counts(p)[1]})" for p in ranked[1:]
    )
    intro = [
        f"오늘 후보 {len(picks)}건 중 이 물건을 1픽으로 짚었습니다. {why}",
    ]
    if others:
        intro.append(f"차순위 후보는 {others} — 리스크 등급 기준으로 확인 부담이 더 큽니다. 전체 후보는 수익 스크리너 탭에서 볼 수 있습니다.")
    if best["kind"] == "auction":
        steps, plan = _coach_auction(best, raw)
    else:
        steps, plan = _coach_urgent(best, raw)
    return {
        "pickKind": best["kind"],
        "date": today.isoformat(),
        "headline": f"오늘의 1픽 — {best['kindLabel']}",
        "intro": intro,
        "steps": steps,
        "plan": plan,
    }


PICKS_PATH = config.CACHE_DIR / "screener_picks.json"
PICK_COOLDOWN_DAYS = 14  # 같은 물건을 이 기간 안에 다시 추천하지 않는다


def _load_picks() -> dict[str, str]:
    if PICKS_PATH.exists():
        try:
            return json.loads(PICKS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_picks(picks: dict[str, str], today: date) -> None:
    # 30일 지난 이력은 정리한다
    keep = {
        k: v
        for k, v in picks.items()
        if (today - date.fromisoformat(v)).days <= 30
    }
    PICKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PICKS_PATH.write_text(
        json.dumps(keep, ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8"
    )


def _fresh(history: dict[str, str], key: str, today: date) -> bool:
    prev = history.get(key)
    if prev is None:
        return True
    days = (today - date.fromisoformat(prev)).days
    # 오늘 이미 뽑힌 물건은 같은 날 재실행(assemble 재시도)에서 그대로 유지한다.
    return days == 0 or days > PICK_COOLDOWN_DAYS


def _daily_picks(urgent: list[dict], auction_top: list[dict], today: date) -> tuple[list[dict], dict[str, dict]]:
    """유형별(아파트·상가·토지 급매 + 공매) 오늘의 추천 1건씩과 원본 행.

    최근 14일 내 추천한 물건은 건너뛰어 매일 새 물건이 올라온다.
    급매 쪽은 '직거래 의심·지분·저층' 태그가 없는 후보를 우선한다.
    두 번째 반환값(kind → 원본 행)은 코칭 문장 생성에 쓴다.
    """
    history = _load_picks()
    picks: list[dict] = []
    raws: dict[str, dict] = {}

    for kind in ("apt", "commercial", "land"):
        pool = [u for u in urgent if u["kind"] == kind]
        clean = [
            u for u in pool
            if not any(("의심" in t or "지분" in t or t == "저층") for t in u["tags"])
        ]
        for u in clean + pool:  # 깨끗한 후보 우선, 없으면 전체에서
            key = f"{kind}|{u['region']}|{u['complex']}|{u['area']}"
            if not _fresh(history, key, today):
                continue
            gap = u["median"] - u["amount"]
            reason = (
                f"같은 {'단지 ' + str(u['area']) + '㎡ 면적대' if kind == 'apt' else '물건 기준'} "
                f"시세 {u['median']/10000:.1f}억 대비 {u['amount']/10000:.1f}억에 신고 — "
                f"{abs(u['drop']):.0f}% 낮은 가격(차액 {gap/10000:.1f}억), 표본 {u['sampleN']}건 기준."
            )
            history[key] = today.isoformat()
            band = u.get("band", {})
            factors = [
                ("할인 폭", f"{abs(u['drop']):.1f}%",
                 "같은 기준(면적대/물건) 시세 대비 낮게 신고된 정도"),
                ("표본 신뢰도", f"{u['sampleN']}건",
                 "비교에 쓴 최근 3개월 거래 수 — 많을수록 시세 기준이 단단함"),
            ]
            evidence = []
            if kind == "apt" and band:
                evidence = [
                    ("면적대 최저~최고", f"{band['min']/10000:.2f}억 ~ {band['max']/10000:.2f}억"),
                    ("면적대 중위가", f"{band['median']/10000:.2f}억"),
                    ("이번 거래", f"{u['amount']/10000:.2f}억"
                     + (" — 표본 중 최저가" if u['amount'] <= band['min'] else "")),
                    ("단지 3개월 거래", f"{band.get('complexDeals', 0)}건 (최근 {band.get('lastYm','')[:4]}.{band.get('lastYm','')[4:]})"),
                ]
                if band.get("buildYear"):
                    evidence.append(("건축년도", str(band["buildYear"])))
                if band.get("pricePerPyeong"):
                    factors.append(("면적대 평당가", f"{band['pricePerPyeong']:,.0f}만/평",
                                    "동일 면적대 시세의 평당 환산값"))
            elif band:
                evidence = [
                    ("물건 내 단가 분포", f"{band['unitMin']:,}~{band['unitMax']:,}만/㎡ (중위 {band['unitMedian']:,})"),
                    ("이번 거래 단가", f"{band['unit']:,}만/㎡"),
                    ("물건 3개월 거래", f"{band.get('complexDeals', 0)}건"),
                ]
            analysis = {
                "factors": factors,
                "evidence": evidence,
                "profit": _profit_urgent(u),
                "risks": _risks_urgent(u, today.year),
                "checklist": CHECKLISTS[kind],
                "verdict": reason,
            }
            picks.append({
                "kind": kind,
                "kindLabel": u["kindLabel"] + " 급매",
                "tab": kind,
                "title": u["complex"],
                "sub": f"{u['region']} {u['umd']} · {u['area']}㎡"
                + (f" {u['floor']}층" if u.get("floor") is not None else ""),
                "headline": f"{u['drop']:.1f}%",
                "metrics": [
                    ("거래가", f"{u['amount']/10000:.2f}억"),
                    ("시세 기준", f"{u['median']/10000:.2f}억"),
                    ("거래일", u["dealtAt"]),
                ],
                "reason": reason,
                "analysis": analysis,
                "tags": u["tags"],
                "lat": u["lat"],
                "lng": u["lng"],
            })
            raws[kind] = u
            break

    for s in auction_top:
        if any("의심" in t or "문제물건" in t for t in s["tags"]):
            continue
        key = f"auction|{s['mgmtNo']}"
        if not _fresh(history, key, today):
            continue
        parts = [f"감정가 {s['appraisal']/10000:.1f}억 물건을 최저 {s['minBid']/10000:.2f}억"
                 f"({s['bidRate']:.0f}%)에 입찰 가능"]
        if s["failCount"]:
            parts.append(f"유찰 {s['failCount']}회로 체감이 검증된 할인")
        if s["liquidity"]:
            parts.append(f"동네 3개월 거래 {s['liquidity']}건으로 환금성 근거 있음")
        if "수의계약" in s["status"]:
            parts.append("수의계약 가능")
        history[key] = today.isoformat()
        f = s.get("factors", {}) if isinstance(s, dict) else {}
        analysis = {
            "factors": [
                ("P — 할인", f"{f.get('P', 0):.2f}",
                 "감정가 대비 최저입찰가 할인 폭 (80% 초과 할인은 상한 처리)"),
                ("L — 유동성", f"{f.get('L', 0):.2f}",
                 f"같은 동네·자산군 3개월 거래 {s['liquidity']}건 기반 환금성 (20건 이상 만점)"),
                ("R — 리스크 보정", f"{f.get('R', 0):.2f}",
                 "유찰 이력·지분 신호·자산군 환금성 가중을 곱한 값"),
                ("종합", f"{s['score']:.1f}점", "100 × P × L × R"),
            ],
            "evidence": [
                ("감정가 → 최저입찰", f"{s['appraisal']/10000:.2f}억 → {s['minBid']/10000:.2f}억 ({s['bidRate']:.0f}%)"),
                ("유찰 이력", f"{s['failCount']}회 — 회당 약 10%p 체감과 정합"),
                ("동네 거래(3개월)", f"{s['liquidity']}건"),
                ("상태", s["status"] + (f" · 마감 {s['closeAt']}" if s["closeAt"] else "")),
                ("관리번호", s["mgmtNo"]),
            ],
            "profit": _profit_auction(s, CAT2KIND.get(s["category"], "commercial")),
            "risks": _risks_auction(s),
            "checklist": CHECKLISTS["auction"],
            "verdict": " · ".join(parts) + ".",
        }
        picks.append({
            "kind": "auction",
            "kindLabel": "공매",
            "tab": "auction",
            "title": s["name"],
            "sub": f"{s['region']} {s['umd']} · {s['category']}"
            + (f" · 마감 {s['closeAt']}" if s["closeAt"] else ""),
            "headline": f"{s['score']:.0f}점",
            "metrics": [
                ("최저입찰", f"{s['minBid']/10000:.2f}억"),
                ("감정가", f"{s['appraisal']/10000:.2f}억"),
                ("최저가율", f"{s['bidRate']:.0f}%"),
            ],
            "reason": " · ".join(parts) + ".",
            "analysis": analysis,
            "tags": s["tags"],
            "lat": s["lat"],
            "lng": s["lng"],
        })
        raws["auction"] = s
        break

    _save_picks(history, today)
    return picks, raws


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
    picks, raws = _daily_picks(urgent, auction_top, today)
    payload = {
        "generatedAt": today.isoformat(),
        "dailyPicks": picks,
        "coach": _coach(picks, raws, today),
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
