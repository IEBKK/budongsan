import {
  formatAmount,
  formatDaysToClose,
  formatPpp,
  formatYm,
  pyeong,
  shortCategory,
} from '../lib/format'
import { CLOSING_SOON_DAYS } from '../lib/filter'
import { isAuction, type PropertyType, type VisibleAuction, type VisibleItem, type VisibleTrade } from '../types'

interface Props {
  type: PropertyType
  items: VisibleItem[]
  loading: boolean
  zoomedOut: boolean
  selectedId: string | null
  onSelect: (item: VisibleItem) => void
  onHover: (id: string | null) => void
}

const PAGE = 60

const UNIT_LABEL: Record<PropertyType, string> = {
  apt: '단지',
  commercial: '건물',
  land: '묶음',
  auction: '물건',
}

function TradeCard({ item }: { item: VisibleTrade }) {
  const meta = item.extra
  return (
    <>
      <div className="card-top">
        <span className="card-name">{item.name}</span>
        <span className="card-price">{formatAmount(item.filteredMedian)}</span>
      </div>
      <div className="card-sub">
        <span>
          {item.regionName} {item.umd}
        </span>
        <span>{formatPpp(item.filteredPpp)}</span>
      </div>
      <div className="card-meta">
        <span>{item.filteredCount}건</span>
        {item.kind === 'apt' && (
          <span>{item.buildYear ? `${item.buildYear}년 준공` : '준공년도 미상'}</span>
        )}
        {item.kind === 'commercial' && meta.use && <span>{meta.use}</span>}
        {item.kind === 'commercial' && meta.buildingType && <span>{meta.buildingType}</span>}
        {item.kind === 'land' && meta.jimok && <span>지목 {meta.jimok}</span>}
        {item.kind === 'land' && <span>{pyeong(item.medianArea)}평</span>}
        {meta.landUse && item.kind !== 'apt' && <span className="tag-soft">{meta.landUse}</span>}
        <span>최근 {formatYm(item.lastYm)}</span>
        {item.geo === 'approx' && (
          <span className="tag-approx" title="정밀 좌표 미확보 — 시군구 중심 근사">
            위치 근사
          </span>
        )}
      </div>
    </>
  )
}

function AuctionCard({ item }: { item: VisibleAuction }) {
  const closing = item.daysToClose !== null && item.daysToClose >= 0 && item.daysToClose <= CLOSING_SOON_DAYS
  return (
    <>
      <div className="card-top">
        <span className="card-name">
          {item.isNew && <em className="tag-new">NEW</em>}
          {item.name}
        </span>
        <span className="card-price">{formatAmount(item.minBid)}</span>
      </div>
      <div className="card-sub">
        <span>
          {item.regionName} {item.umd}
        </span>
        <span>{item.bidRate !== null ? `감정가의 ${Math.round(item.bidRate)}%` : '감정가 미상'}</span>
      </div>
      <div className="card-meta">
        <span>{shortCategory(item.category)}</span>
        {item.failCount > 0 && <span className="tag-soft">{item.failCount}회 유찰</span>}
        <span className={closing ? 'tag-closing' : undefined}>{formatDaysToClose(item.daysToClose)}</span>
        {item.geo === 'approx' && (
          <span className="tag-approx" title="정밀 좌표 미확보 — 시군구 중심 근사">
            위치 근사
          </span>
        )}
      </div>
    </>
  )
}

export default function ListPanel({
  type,
  items,
  loading,
  zoomedOut,
  selectedId,
  onSelect,
  onHover,
}: Props) {
  if (zoomedOut) {
    return (
      <div className="list-empty">
        <p>지도를 확대하면 개별 물건이 표시됩니다.</p>
        <p className="hint">현재는 시군구 단위 집계 마커만 보여집니다.</p>
      </div>
    )
  }
  if (loading && !items.length) return <div className="list-empty">불러오는 중…</div>
  if (!items.length) {
    return (
      <div className="list-empty">
        <p>이 영역에 조건을 만족하는 물건이 없습니다.</p>
        <p className="hint">지도를 옮기거나 필터를 완화해 보세요.</p>
      </div>
    )
  }

  return (
    <>
      <div className="list-head">
        이 영역 <b>{items.length.toLocaleString()}</b>개 {UNIT_LABEL[type]}
        {items.length > PAGE && <span className="hint"> · 상위 {PAGE}개 표시</span>}
      </div>
      <ul className="list" onMouseLeave={() => onHover(null)}>
        {items.slice(0, PAGE).map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className={`card${item.id === selectedId ? ' selected' : ''}`}
              onClick={() => onSelect(item)}
              onMouseEnter={() => onHover(item.id)}
            >
              {isAuction(item) ? <AuctionCard item={item} /> : <TradeCard item={item} />}
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}
