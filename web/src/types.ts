export type PropertyType = 'apt' | 'commercial' | 'land' | 'auction'
export type TradeType = Exclude<PropertyType, 'auction'>

export interface Meta {
  generatedAt: string
  dataAsOf: string
  months: string[]
  source: string
  mock: boolean
  regionCount: number
  dealCount: number
  dealCountByType: Partial<Record<TradeType, number>>
  auction: AuctionSummary | null
  failedRegions: string[]
  /** 오늘 갱신되지 못한(또는 없는) 지역 파일 수 — 권역 분할 수집의 구멍 감지용 */
  staleCount?: number
  geocode: { cached: number; lookups: number; approximated: number; pendingExact: number }
  types: Record<PropertyType, boolean>
}

export interface AuctionSummary {
  count: number
  newCount: number
  avgBidRate: number | null
  medianBidRate: number | null
  avgFailCount: number
}

export interface MonthlyPoint {
  ym: string
  count: number
  pricePerPyeong: number
}

export interface RegionSummary {
  code: string
  sido: string
  name: string
  lat: number
  lng: number
  complexCount: number
  dealCount: number
  pricePerPyeong: number
  medianAmount: number
  momPct: number | null
  monthly: MonthlyPoint[]
}

export interface AreaStat {
  label: string
  areaM2: number
  pyeong: number
  count: number
  medianAmount: number
  minAmount: number
  maxAmount: number
  pricePerPyeong: number
}

export interface Deal {
  ym: string
  day: number
  amount: number
  area: number
  floor: number | null
  /** 토지 전용: 지분거래 구분 */
  share?: string
}

/** 유형별 고유 항목. 상가=use/buildingType/landUse/plottageAr, 토지=jimok/landUse */
export interface TradeExtra {
  use?: string
  buildingType?: string
  landUse?: string
  plottageAr?: number
  jimok?: string
  shareType?: string
  dong?: string
}

/** 아파트·상가·토지 공통. 지도 마커 1개 = 이 항목 1개 */
export interface TradeItem {
  kind: TradeType
  id: string
  name: string
  umd: string
  jibun: string
  roadName: string
  buildYear: number | null
  lat: number
  lng: number
  geo: 'exact' | 'approx'
  dealCount: number
  medianAmount: number
  minAmount: number
  maxAmount: number
  pricePerPyeong: number
  lastYm: string
  medianArea: number
  minArea: number
  maxArea: number
  extra: TradeExtra
  areas: AreaStat[]
  series: MonthlyPoint[]
  deals: Deal[]
}

export interface TradeFile {
  kind: TradeType
  code: string
  name: string
  months: string[]
  generatedAt: string
  items: TradeItem[]
}

/** 온비드 공매 물건. 법원경매는 미포함 (PRD 3.2-D Phase 1) */
export interface AuctionItem {
  kind: 'auction'
  id: string
  key: string
  name: string
  category: string
  address: string
  regionCode: string
  regionName: string
  umd: string
  lat: number
  lng: number
  geo: 'exact' | 'approx'
  /** 만원 단위 */
  minBid: number
  appraisal: number
  /** 최저가 / 감정가 (%) */
  bidRate: number | null
  failCount: number
  beginAt: string
  closeAt: string
  status: string
  disposal: string
  bidMethod: string
  institution: string
  firstSeen: string
  isNew: boolean
  extra: { roadAddress?: string; feeRate?: number; mgmtNo?: string }
}

export interface AuctionFile {
  kind: 'auction'
  source: string
  scope: string
  generatedAt: string
  summary: AuctionSummary
  outOfScopeCount: number
  items: AuctionItem[]
}

/** 필터가 반영되어 실제로 지도·리스트에 그려지는 항목 */
export interface VisibleTrade extends TradeItem {
  regionCode: string
  regionName: string
  filteredCount: number
  filteredMedian: number
  filteredPpp: number
}

export interface VisibleAuction extends AuctionItem {
  /** 마감까지 남은 일수. 지난 물건은 음수 */
  daysToClose: number | null
}

export type VisibleItem = VisibleTrade | VisibleAuction

export function isAuction(item: VisibleItem): item is VisibleAuction {
  return item.kind === 'auction'
}

export type AuctionStatusFilter = 'all' | 'new' | 'closing'

export interface Filters {
  /** 실거래 3종: 최근 N개월 */
  months: number
  /** 실거래=거래가, 경매=최저입찰가 (만원) */
  minAmount: number | null
  maxAmount: number | null
  /** 실거래 전용 (m2) */
  minArea: number | null
  maxArea: number | null
  /** 경매 전용 */
  auctionStatus: AuctionStatusFilter
  maxBidRate: number | null
  minFailCount: number | null
}

export interface SearchItem {
  i: string
  n: string
  a: string
  c: string
  y: number
  x: number
}
