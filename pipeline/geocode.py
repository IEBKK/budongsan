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
        for provider in (self._vworld, self._kakao):
            try:
                coord = provider(address)
            except Exception:  # noqa: BLE001 - 지오코딩 실패는 근사로 강등하고 계속 간다
                coord = None
            if coord:
                time.sleep(0.05)
                return coord
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
