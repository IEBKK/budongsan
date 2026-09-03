import { useEffect, useMemo, useState } from 'react'
import { ensureRegion, fetchAuction, fetchNationSummary } from '../lib/api'
import { applyAuctionFilters, applyTradeFilters, cutoffYm } from '../lib/filter'
import type {
  AuctionFile,
  Filters,
  PropertyType,
  RegionSummary,
  TradeFile,
  TradeType,
  VisibleItem,
} from '../types'

export interface ViewState {
  zoom: number
  north: number
  south: number
  east: number
  west: number
}

/** 이 줌 미만에서는 시군구 집계 마커만 보여준다 (MAP-02) */
export const REGION_ZOOM_MAX = 12

// 시군구 중심좌표만 알고 있으므로, 경계 밖 중심을 가진 인접 구도 넉넉히 포함한다.
const PAD_LAT = 0.09
const PAD_LNG = 0.11

export function regionsInView(regions: RegionSummary[], view: ViewState | null): RegionSummary[] {
  if (!view) return []
  return regions.filter(
    (r) =>
      r.lat <= view.north + PAD_LAT &&
      r.lat >= view.south - PAD_LAT &&
      r.lng <= view.east + PAD_LNG &&
      r.lng >= view.west - PAD_LNG,
  )
}

function inBounds(p: { lat: number; lng: number }, view: ViewState): boolean {
  return p.lat <= view.north && p.lat >= view.south && p.lng <= view.east && p.lng >= view.west
}

// 매 렌더마다 새 배열을 만들면 이 값에 걸린 useMemo 체인이 전부 무효화되어
// 렌더 루프가 돈다. 빈 상태는 반드시 같은 참조를 돌려준다.
const NO_REGIONS: RegionSummary[] = []

/** 전국 시군구 요약. 유형을 바꾸면 그 유형의 요약으로 갈아탄다. */
export function useNationSummary(type: PropertyType) {
  const [byType, setByType] = useState<Partial<Record<TradeType, RegionSummary[]>>>({})
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (type === 'auction' || byType[type]) return
    let cancelled = false
    fetchNationSummary(type)
      .then((d) => !cancelled && setByType((prev) => ({ ...prev, [type]: d.regions })))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [type, byType])

  const regions = useMemo(
    () => (type === 'auction' ? NO_REGIONS : byType[type] ?? NO_REGIONS),
    [type, byType],
  )

  return { regions, error }
}

/**
 * MAP-01: 현재 영역에 걸친 시군구 JSON만 lazy load 하고, 그 안에서 다시
 * bounding box + 필터를 통과한 항목만 돌려준다. 리스트와 지도는 이 배열 하나를 공유해
 * 항상 동기화된다 (MAP-04).
 *
 * 공매는 전국 물건 수가 적어 파일 1개를 한 번만 받고, 줌 단계와 무관하게 항상 표시한다.
 */
export function useVisibleData(
  type: PropertyType,
  nation: RegionSummary[],
  view: ViewState | null,
  filters: Filters,
) {
  const [files, setFiles] = useState<Record<string, TradeFile>>({})
  const [auction, setAuction] = useState<AuctionFile | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const visibleRegions = useMemo(() => regionsInView(nation, view), [nation, view])
  const needCodes = useMemo(
    () =>
      type !== 'auction' && view && view.zoom > REGION_ZOOM_MAX
        ? visibleRegions.map((r) => r.code)
        : [],
    [visibleRegions, view, type],
  )
  const needKey = `${type}|${needCodes.join(',')}`

  useEffect(() => {
    if (type !== 'auction' || auction) return
    let cancelled = false
    setLoading(true)
    fetchAuction()
      .then((d) => !cancelled && setAuction(d))
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [type, auction])

  useEffect(() => {
    if (type === 'auction') return
    const missing = needCodes.filter((c) => !files[`${type}/${c}`])
    if (!missing.length) return
    let cancelled = false
    setLoading(true)
    Promise.allSettled(missing.map((code) => ensureRegion(type as TradeType, code)))
      .then((results) => {
        if (cancelled) return
        const next: Record<string, TradeFile> = {}
        let failed = 0
        for (const r of results) {
          if (r.status === 'fulfilled') next[`${type}/${r.value.code}`] = r.value
          else failed += 1
        }
        if (Object.keys(next).length) setFiles((prev) => ({ ...prev, ...next }))
        setError(failed ? `${failed}개 지역 데이터를 불러오지 못했습니다.` : null)
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // files 를 의존성에 넣으면 setFiles 마다 재실행되므로 needKey 로만 트리거한다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needKey])

  const items = useMemo<VisibleItem[]>(() => {
    if (!view) return []

    if (type === 'auction') {
      if (!auction) return []
      const out = auction.items
        .filter((i) => inBounds(i, view))
        .map((i) => applyAuctionFilters(i, filters))
        .filter((i): i is NonNullable<typeof i> => i !== null)
      // 최저가율이 낮을수록(유찰 누적) 먼저 — 파이프라인 정렬과 같은 기준
      out.sort((a, b) => (a.bidRate ?? 999) - (b.bidRate ?? 999) || b.failCount - a.failCount)
      return out
    }

    if (view.zoom <= REGION_ZOOM_MAX) return []
    const cutoff = cutoffYm(filters.months)
    const out: VisibleItem[] = []
    for (const region of visibleRegions) {
      const file = files[`${type}/${region.code}`]
      if (!file) continue
      for (const item of file.items) {
        if (!inBounds(item, view)) continue
        const v = applyTradeFilters(item, region, filters, cutoff)
        if (v) out.push(v)
      }
    }
    out.sort((a, b) => {
      if (a.kind === 'auction' || b.kind === 'auction') return 0
      return b.filteredCount - a.filteredCount || b.filteredMedian - a.filteredMedian
    })
    return out
  }, [type, auction, files, visibleRegions, view, filters])

  const pendingRegions = needCodes.filter((c) => !files[`${type}/${c}`]).length

  return { items, visibleRegions, loading, pendingRegions, error, auctionFile: auction }
}
