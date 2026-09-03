"""주소 -> 좌표 (5.2).

실거래가 API는 좌표를 주지 않는다. 신규 주소만 외부 지오코더에 물어보고
결과는 저장소에 캐시로 남겨 일일 호출량을 최소화한다.
키가 없으면 시군구 중심좌표 + 주소 해시 기반 결정적 오프셋으로 근사하며,
그 좌표는 geo="approx" 로 표시되어 UI에서 구분된다.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from . import config

CACHE_PATH = config.CACHE_DIR / "geocode.json"
APPROX_RADIUS_M = 900  # 시군구 중심 주변 분산 반경
GEOCODE_BUDGET_SEC = 480   # 지오코딩 전체 시간 예산. 초과하면 남은 주소는 근사로 넘긴다.
PROVIDER_TRIP_COUNT = 5    # 제공자 연속 예외 횟수 상한. 초과하면 그 제공자를 끈다.


class Geocoder:
    def __init__(self, session=None, enabled: bool = True, refresh_approx: bool = False):
        self.session = session
        self.enabled = enabled
        # 키가 새로 생겼을 때, 이미 캐시된 근사 좌표를 정밀 좌표로 승격한다.
        # 기본값이 False 인 이유: 지오코더가 끝내 찾지 못하는 주소를 매일 재조회하면
        # 무료 쿼터만 태운다.
        self.refresh_approx = refresh_approx
        self.cache: dict[str, dict] = {}
        self.hits = 0
        self.lookups = 0
        self.approximated = 0
        # 러너 IP 가 지오코더에서 차단되면 수천 주소 × 실패 응답으로 잡이 타임아웃난다
        # (2026-09-03 VWorld 가 GitHub 러너를 차단하는 것을 확인). 예산·서킷브레이커로 막는다.
        self._deadline: float | None = None
        self._fails = {"vworld": 0, "kakao": 0}
        self._dead: set[str] = set()
        if CACHE_PATH.exists():
            try:
                self.cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.cache = {}

    # --- public -------------------------------------------------------
    def resolve(self, region, umd: str, jibun: str) -> tuple[float, float, str]:
        key = f"{region.code}|{umd}|{jibun}"
        cached = self.cache.get(key)
        stale_approx = (
            cached is not None
            and cached.get("geo") == "approx"
            and self.enabled
            and self.refresh_approx
        )
        if cached and not stale_approx:
            self.hits += 1
            return cached["lat"], cached["lng"], cached.get("geo", "exact")

        coord = None
        if self.enabled:
            address = f"{region.sido} {region.name} {umd} {jibun}".strip()
            coord = self._lookup(address)
            self.lookups += 1

        if coord is None:
            lat, lng = self._approximate(region, key)
            geo = "approx"
            self.approximated += 1
        else:
            lat, lng = coord
            geo = "exact"

        # approx 좌표도 캐시에 넣되 geo 표시를 남겨, 나중에 키가 생기면
        # geo=="approx" 항목만 다시 조회하면 된다.
        self.cache[key] = {"lat": round(lat, 6), "lng": round(lng, 6), "geo": geo}
        return lat, lng, geo

    def refreshable_count(self) -> int:
        return sum(1 for v in self.cache.values() if v.get("geo") == "approx")

    def save(self) -> None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(self.cache, ensure_ascii=False, sort_keys=True, indent=0),
            encoding="utf-8",
        )

    # --- providers ----------------------------------------------------
    def _lookup(self, address: str) -> tuple[float, float] | None:
        import sys

        if self._deadline is None:
            self._deadline = time.monotonic() + GEOCODE_BUDGET_SEC
        elif time.monotonic() > self._deadline:
            if self.enabled:
                print(
                    f"  지오코딩 시간 예산({GEOCODE_BUDGET_SEC}s) 초과 — 남은 주소는 근사 처리",
                    file=sys.stderr,
                )
            self.enabled = False
            return None

        for name, provider in (("vworld", self._vworld), ("kakao", self._kakao)):
            if name in self._dead:
                continue
            try:
                coord = provider(address)
                self._fails[name] = 0
            except Exception as exc:  # noqa: BLE001 - 지오코딩 실패는 근사로 강등하고 계속 간다
                coord = None
                self._fails[name] += 1
                if self._fails[name] >= PROVIDER_TRIP_COUNT:
                    self._dead.add(name)
                    # 예외 메시지에는 키가 든 URL 이 섞일 수 있어 타입만 남긴다.
                    print(
                        f"  지오코더 {name} 연속 {PROVIDER_TRIP_COUNT}회 실패({type(exc).__name__}) — 비활성화",
                        file=sys.stderr,
                    )
            if coord:
                time.sleep(0.05)
                return coord
        if self._dead.issuperset({"vworld", "kakao"}):
            self.enabled = False
        return None

    def _vworld(self, address: str) -> tuple[float, float] | None:
        if not (config.VWORLD_KEY and self.session):
            return None
        resp = self.session.get(
            "https://api.vworld.kr/req/address",
            params={
                "service": "address",
                "request": "getcoord",
                "version": "2.0",
                "crs": "epsg:4326",
                "type": "PARCEL",
                "address": address,
                "format": "json",
                "key": config.VWORLD_KEY,
            },
            timeout=config.REQUEST_TIMEOUT,
        )
        data = resp.json().get("response", {})
        if data.get("status") != "OK":
            return None
        point = data["result"]["point"]
        return float(point["y"]), float(point["x"])

    def _kakao(self, address: str) -> tuple[float, float] | None:
        if not (config.KAKAO_REST_KEY and self.session):
            return None
        resp = self.session.get(
            "https://dapi.kakao.com/v2/local/search/address.json",
            params={"query": address},
            headers={"Authorization": f"KakaoAK {config.KAKAO_REST_KEY}"},
            timeout=config.REQUEST_TIMEOUT,
        )
        docs = resp.json().get("documents") or []
        if not docs:
            return None
        return float(docs[0]["y"]), float(docs[0]["x"])

    # --- fallback -----------------------------------------------------
    @staticmethod
    def _approximate(region, key: str) -> tuple[float, float]:
        h = hashlib.sha1(key.encode("utf-8")).digest()
        angle = (h[0] << 8 | h[1]) / 65535 * 2 * math.pi
        radius = ((h[2] << 8 | h[3]) / 65535) ** 0.5 * APPROX_RADIUS_M
        dlat = (radius * math.cos(angle)) / 111_320
        dlng = (radius * math.sin(angle)) / (111_320 * math.cos(math.radians(region.lat)))
        return region.lat + dlat, region.lng + dlng
