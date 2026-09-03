"""파이프라인 전역 설정. 값은 전부 환경변수로 주입한다 (GitHub Secrets 호환)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = Path(__file__).resolve().parent / "seed"
CACHE_DIR = Path(__file__).resolve().parent / "cache"


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


@dataclass(frozen=True)
class Region:
    code: str
    sido: str
    name: str
    lat: float
    lng: float

    @property
    def full_name(self) -> str:
        return f"{self.sido} {self.name}"


def load_regions() -> list[Region]:
    raw = json.loads((SEED_DIR / "regions.json").read_text(encoding="utf-8"))
    regions = [Region(**r) for r in raw["regions"]]
    only = _env("TARGET_REGIONS")
    if only:
        wanted = {c.strip() for c in only.split(",") if c.strip()}
        regions = [r for r in regions if r.code in wanted]
        missing = wanted - {r.code for r in regions}
        if missing:
            raise SystemExit(f"TARGET_REGIONS에 seed/regions.json에 없는 코드가 있다: {sorted(missing)}")
    return regions


def region_by_address(regions: list[Region], address: str) -> Region | None:
    """온비드 주소 문자열에서 시군구를 찾아낸다.

    seed/regions.json 범위(현재 서울) 밖 물건은 좌표를 붙일 수 없어 None 을 돌려주고,
    호출측에서 제외 건수를 meta 에 남긴다.
    """
    if not address:
        return None
    for r in regions:
        # '서울특별시 강남구 …' / '서울 강남구 …' 두 표기를 모두 받는다.
        if r.name in address and (r.sido in address or r.sido[:2] in address):
            return r
    return None


def rolling_months(today: date | None = None) -> list[str]:
    """DATA-03: 신고 지연(최대 30일) 때문에 최근 N개월을 매일 재수집한다."""
    n = max(1, int(_env("ROLLING_MONTHS", "3")))
    today = today or date.today()
    out: list[str] = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


MOLIT_SERVICE_KEY = _env("MOLIT_SERVICE_KEY")
ONBID_SERVICE_KEY = _env("ONBID_SERVICE_KEY")
VWORLD_KEY = _env("VWORLD_KEY")
KAKAO_REST_KEY = _env("KAKAO_REST_KEY")
OUT_DIR = ROOT / _env("OUT_DIR", "web/public/data")
REQUEST_TIMEOUT = int(_env("REQUEST_TIMEOUT", "20"))
