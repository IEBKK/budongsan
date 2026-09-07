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


def _daily_picks(urgent: list[dict], auction_top: list[dict], today: date) -> list[dict]:
    """유형별(아파트·상가·토지 급매 + 공매) 오늘의 추천 1건씩.

    최근 14일 내 추천한 물건은 건너뛰어 매일 새 물건이 올라온다.
    급매 쪽은 '직거래 의심·지분·저층' 태그가 없는 후보를 우선한다.
    """
    history = _load_picks()
    picks: list[dict] = []

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
        break

    _save_picks(history, today)
    return picks


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
        "dailyPicks": _daily_picks(urgent, auction_top, today),
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
