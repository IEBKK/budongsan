"""M1/M3 파이프라인 진입점.

  python3 -m pipeline.build                      # 실 API 수집 (키 필요)
  python3 -m pipeline.build --mock               # 합성 데이터로 산출물 생성 (키 불필요)
  python3 -m pipeline.build --types apt,auction  # 일부 유형만
  python3 -m pipeline.build --regions 11680,11650

산출물은 OUT_DIR(기본 web/public/data) 아래에 쓰이고, 그대로 정적 배포된다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone

from . import config, mock, transform
from .geocode import Geocoder
from .sources import molit_apt, molit_commercial, molit_land, onbid

KST = timezone(timedelta(hours=9))
SIZE_WARN_BYTES = 1_000_000  # 3.4 파일당 목표 크기
AUCTION_SEEN_PATH = config.CACHE_DIR / "auction_seen.json"

# 시군구 단위로 수집되는 실거래가 3종. (출력 디렉터리, 실 수집 함수, 모의 생성 함수)
TRADE_TYPES = {
    "apt": ("apt", molit_apt.fetch_month, mock.generate_apt),
    "commercial": ("commercial", molit_commercial.fetch_month, mock.generate_commercial),
    "land": ("land", molit_land.fetch_month, mock.generate_land),
}
ALL_TYPES = [*TRADE_TYPES, "auction"]


def write_json(path, payload) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    size = len(text.encode("utf-8"))
    if size > SIZE_WARN_BYTES:
        print(f"  [warn] {path.name} {size/1e6:.2f} MB — 분할 기준 재검토 필요")
    return size


def load_seen() -> dict[str, str]:
    if AUCTION_SEEN_PATH.exists():
        try:
            return json.loads(AUCTION_SEEN_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_seen(seen: dict[str, str], keep_keys: set[str]) -> None:
    """종료된 물건 키가 무한히 쌓이지 않도록, 이번에 본 것만 남긴다."""
    AUCTION_SEEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    pruned = {k: v for k, v in seen.items() if k in keep_keys}
    AUCTION_SEEN_PATH.write_text(
        json.dumps(pruned, ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8"
    )


def collect_trade_type(
    kind: str, regions, months, args, session, geocoder
) -> tuple[list[dict], list[dict], int, int, list[str]]:
    """실거래가 1종을 전 지역 수집·집계하고 지역별 JSON 을 쓴다."""
    out_dir, fetch, make_mock = TRADE_TYPES[kind]
    summary: list[dict] = []
    search_index: list[dict] = []
    failed: list[str] = []
    total_deals = 0
    total_bytes = 0

    for idx, region in enumerate(regions, 1):
        try:
            if args.mock:
                deals = make_mock(region, months)
            else:
                deals = []
                for ym in months:
                    deals.extend(fetch(session, region.code, ym))
        except Exception as exc:  # noqa: BLE001 - 한 지역 실패가 전체를 막지 않게 한다
            print(f"  [{idx}/{len(regions)}] {region.name} 실패: {exc}", file=sys.stderr)
            failed.append(f"{kind}/{region.code} {region.name}: {exc}")
            continue

        items = transform.build_trade_items(
            deals, region, lambda d, r=region: geocoder.resolve(r, d.umd, d.jibun), kind=kind
        )
        size = write_json(
            config.OUT_DIR / out_dir / f"{region.code}.json",
            {
                "kind": kind,
                "code": region.code,
                "name": region.full_name,
                "months": months,
                "generatedAt": datetime.now(KST).isoformat(timespec="seconds"),
                "items": items,
            },
        )
        total_bytes += size
        total_deals += len(deals)
        summary.append(transform.build_region_summary(region, items, months))
        if kind == "apt":
            # 검색 인덱스는 단지명 검색이 의미 있는 아파트만 담는다 (파일 크기 억제).
            search_index.extend(transform.build_search_index(region, items))
        print(
            f"  [{idx}/{len(regions)}] {region.name:6s} 거래 {len(deals):5d} / 항목 {len(items):4d} / {size/1024:6.1f} KB"
        )

    return summary, search_index, total_deals, total_bytes, failed


def collect_auction(regions, args, session, geocoder) -> tuple[dict | None, int, list[str]]:
    """공매(온비드)는 전국 단위 1회 호출 → 전국 1파일."""
    today = datetime.now(KST).date().isoformat()
    try:
        things = mock.generate_auction(regions) if args.mock else onbid.fetch_all(session)
    except Exception as exc:  # noqa: BLE001
        print(f"  공매 수집 실패: {exc}", file=sys.stderr)
        return None, 0, [f"auction: {exc}"]

    seen = load_seen()
    items, skipped = transform.build_auction_items(
        things,
        regions,
        lambda r, umd, jibun: geocoder.resolve(r, umd, jibun),
        seen,
        today,
    )
    save_seen(seen, {t.key for t in things})

    summary = transform.build_auction_summary(items)
    size = write_json(
        config.OUT_DIR / "auction" / "onbid.json",
        {
            "kind": "auction",
            "source": "온비드(한국자산관리공사) 공매",
            "scope": "법원경매 제외 — 공매 물건만 (PRD 3.2-D Phase 1)",
            "generatedAt": datetime.now(KST).isoformat(timespec="seconds"),
            "summary": summary,
            "outOfScopeCount": skipped,
            "items": items,
        },
    )
    print(
        f"  공매 물건 {len(items)}건 (신규 {summary['newCount']}건 / 수집범위 밖 {skipped}건 제외) / {size/1024:.1f} KB"
    )
    return summary, size, []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="부동산 대시보드 데이터 파이프라인")
    parser.add_argument("--mock", action="store_true", help="API 키 없이 합성 데이터 생성")
    parser.add_argument("--regions", default="", help="시군구 코드 콤마 구분 (TARGET_REGIONS 대체)")
    parser.add_argument(
        "--types",
        default=",".join(ALL_TYPES),
        help=f"수집할 유형 콤마 구분 (기본 전체: {','.join(ALL_TYPES)})",
    )
    parser.add_argument("--no-geocode", action="store_true", help="외부 지오코딩 호출 생략")
    parser.add_argument(
        "--refresh-approx",
        action="store_true",
        help="캐시된 근사 좌표를 정밀 좌표로 재조회 (지오코딩 키를 새로 넣은 직후 1회)",
    )
    args = parser.parse_args(argv)

    if args.regions:
        import os

        os.environ["TARGET_REGIONS"] = args.regions

    kinds = [k.strip() for k in args.types.split(",") if k.strip()]
    unknown = [k for k in kinds if k not in ALL_TYPES]
    if unknown:
        print(f"알 수 없는 유형: {unknown}. 가능: {ALL_TYPES}", file=sys.stderr)
        return 2

    started = time.time()
    regions = config.load_regions()
    months = config.rolling_months()
    print(
        f"대상 시군구 {len(regions)}곳 / 롤링 {months[0]}~{months[-1]} / 유형 {','.join(kinds)} / mock={args.mock}"
    )

    session = None
    if not args.mock or not args.no_geocode:
        try:
            import requests

            session = requests.Session()
            session.headers["User-Agent"] = "budongsan-dashboard/0.2 (+github actions)"
        except ImportError:
            if not args.mock:
                print("requests 가 필요하다: pip install -r pipeline/requirements.txt", file=sys.stderr)
                return 2
            print("  [info] requests 미설치 — 지오코딩은 근사 좌표로 대체한다")

    geocoder = Geocoder(
        session=session,
        enabled=not args.no_geocode and session is not None,
        refresh_approx=args.refresh_approx,
    )

    failed: list[str] = []
    total_bytes = 0
    deal_counts: dict[str, int] = {}
    summaries: dict[str, list[dict]] = {}
    auction_summary: dict | None = None
    search_index: list[dict] = []

    for kind in kinds:
        if kind == "auction":
            print("\n[경매·공매] 온비드 공매")
            auction_summary, size, errs = collect_auction(regions, args, session, geocoder)
            total_bytes += size
            failed.extend(errs)
            continue

        print(f"\n[{kind}] 시군구별 수집")
        summary, index, deals, size, errs = collect_trade_type(
            kind, regions, months, args, session, geocoder
        )
        summaries[kind] = summary
        search_index.extend(index)
        deal_counts[kind] = deals
        total_bytes += size
        failed.extend(errs)

    if not summaries and auction_summary is None:
        print("\n수집된 데이터가 없다. 파이프라인 실패로 처리한다.", file=sys.stderr)
        return 1

    geocoder.save()

    # 부분 실행(--types)이 다른 유형의 탭을 꺼버리지 않도록, 활성 여부는
    # '이번에 수집했는가'가 아니라 '산출 파일이 디스크에 있는가'로 판정한다.
    prev_meta = {}
    meta_path = config.OUT_DIR / "meta.json"
    if meta_path.exists():
        try:
            prev_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev_meta = {}

    available = {
        k: any((config.OUT_DIR / TRADE_TYPES[k][0]).glob("*.json")) for k in TRADE_TYPES
    }
    available["auction"] = (config.OUT_DIR / "auction" / "onbid.json").exists()

    # 이번에 안 돌린 유형의 건수·요약은 직전 meta 값을 이어받는다.
    merged_counts = {**prev_meta.get("dealCountByType", {}), **deal_counts}
    merged_auction = auction_summary if auction_summary is not None else prev_meta.get("auction")

    now = datetime.now(KST)
    # DATA-05: '데이터 기준일'은 수집 시각 기준. 실거래 신고 지연은 별도 안내한다.
    meta = {
        "generatedAt": now.isoformat(timespec="seconds"),
        "dataAsOf": now.date().isoformat(),
        "months": months,
        "source": "국토교통부 실거래가 공개시스템 · 온비드(한국자산관리공사) (공공데이터포털)",
        "mock": args.mock,
        "regionCount": len(regions),
        "collectedTypes": kinds,
        "dealCount": sum(merged_counts.values()),
        "dealCountByType": merged_counts,
        "auction": merged_auction,
        "failedRegions": failed,
        "geocode": {
            "cached": geocoder.hits,
            "lookups": geocoder.lookups,
            "approximated": geocoder.approximated,
            "pendingExact": geocoder.refreshable_count(),
        },
        # 프런트 탭 활성화 여부는 이 값이 결정한다.
        "types": {k: available[k] for k in ALL_TYPES},
    }
    total_bytes += write_json(config.OUT_DIR / "meta.json", meta)

    for kind, summary in summaries.items():
        total_bytes += write_json(
            config.OUT_DIR / "summary" / f"{kind}.json", {"kind": kind, "regions": summary}
        )
    if "apt" in summaries:
        # 초기 지도 로딩용 기본 요약 (아파트 기준) — 기존 경로 유지
        total_bytes += write_json(
            config.OUT_DIR / "summary" / "nation.json", {"regions": summaries["apt"]}
        )
    if search_index:
        total_bytes += write_json(config.OUT_DIR / "search-index.json", {"items": search_index})

    print(
        f"\n완료: 유형 {len(kinds)} / 거래 {sum(deal_counts.values())} / 산출 {total_bytes/1024:.1f} KB "
        f"/ {time.time()-started:.1f}s"
    )
    if failed:
        print(f"실패 {len(failed)}건 — meta.json 의 failedRegions 참고", file=sys.stderr)
    # 부분 실패는 배포를 막지 않는다. 전량 실패만 실패 처리(위에서 return 1).
    return 0


if __name__ == "__main__":
    sys.exit(main())
