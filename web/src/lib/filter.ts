import type {
  AuctionItem,
  Deal,
  Filters,
  RegionSummary,
  TradeItem,
  VisibleAuction,
  VisibleTrade,
} from '../types'

export const DEFAULT_FILTERS: Filters = {
  months: 12,
  minAmount: null,
  maxAmount: null,
  minArea: null,
  maxArea: null,
  auctionStatus: 'all',
  maxBidRate: null,
  minFailCount: null,
}

/** 유형을 바꿀 때 가격·면적 조건은 단위가 달라 의미가 없으므로 초기화한다. */
export function resetForType(f: Filters): Filters {
  return { ...DEFAULT_FILTERS, months: f.months }
}

/** 최근 n개월 컷오프(YYYYMM). 데이터가 더 짧으면 자연스럽게 전체가 통과한다. */
export function cutoffYm(months: number, now = new Date()): string {
  const d = new Date(now.getFullYear(), now.getMonth() - (months - 1), 1)
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}`
}

function matches(deal: Deal, f: Filters, cutoff: string): boolean {
  if (deal.ym < cutoff) return false
  if (f.minAmount !== null && deal.amount < f.minAmount) return false
  if (f.maxAmount !== null && deal.amount > f.maxAmount) return false
  if (f.minArea !== null && deal.area < f.minArea) return false
  if (f.maxArea !== null && deal.area > f.maxArea) return false
  return true
}

function median(nums: number[]): number {
  if (!nums.length) return 0
  const s = [...nums].sort((a, b) => a - b)
  const mid = s.length >> 1
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2
}

export function isDefaultTradeFilter(f: Filters): boolean {
  return (
    f.minAmount === null &&
    f.maxAmount === null &&
    f.minArea === null &&
    f.maxArea === null &&
    f.months >= 12
  )
}

/**
 * 항목의 거래 목록에 필터를 적용하고, 통과한 거래만으로 통계를 다시 계산한다.
 * 통과 거래가 없으면 null — 지도와 리스트 양쪽에서 사라진다.
 */
export function applyTradeFilters(
  item: TradeItem,
  region: Pick<RegionSummary, 'code' | 'name'>,
  f: Filters,
  cutoff: string,
): VisibleTrade | null {
  if (isDefaultTradeFilter(f)) {
    return {
      ...item,
      regionCode: region.code,
      regionName: region.name,
      filteredCount: item.dealCount,
      filteredMedian: item.medianAmount,
      filteredPpp: item.pricePerPyeong,
    }
  }
  const kept = item.deals.filter((d) => matches(d, f, cutoff))
  if (!kept.length) return null
  return {
    ...item,
    regionCode: region.code,
    regionName: region.name,
    filteredCount: kept.length,
    filteredMedian: Math.round(median(kept.map((d) => d.amount))),
    filteredPpp: Math.round(median(kept.map((d) => d.amount / (d.area / 3.3058))) * 10) / 10,
  }
}

const DAY_MS = 86_400_000

export function daysUntil(iso: string, now = new Date()): number | null {
  if (!iso) return null
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return null
  return Math.ceil((t - now.getTime()) / DAY_MS)
}

/** 마감 임박 기준 — 입찰 준비 시간을 감안해 7일 */
export const CLOSING_SOON_DAYS = 7

export function applyAuctionFilters(
  item: AuctionItem,
  f: Filters,
  now = new Date(),
): VisibleAuction | null {
  if (f.minAmount !== null && item.minBid < f.minAmount) return null
  if (f.maxAmount !== null && item.minBid > f.maxAmount) return null
  if (f.maxBidRate !== null && (item.bidRate === null || item.bidRate > f.maxBidRate)) return null
  if (f.minFailCount !== null && item.failCount < f.minFailCount) return null

  const daysToClose = daysUntil(item.closeAt, now)
  if (f.auctionStatus === 'new' && !item.isNew) return null
  if (
    f.auctionStatus === 'closing' &&
    (daysToClose === null || daysToClose < 0 || daysToClose > CLOSING_SOON_DAYS)
  ) {
    return null
  }
  return { ...item, daysToClose }
}
