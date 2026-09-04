import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import FilterBar from './components/Filters'
import ListPanel from './components/ListPanel'
import MapView from './components/MapView'
import SearchBox from './components/SearchBox'
import {
  REGION_ZOOM_MAX,
  useNationSummary,
  useVisibleData,
  type ViewState,
} from './hooks/useVisibleData'
import { fetchMeta } from './lib/api'
import { track } from './lib/analytics'
import { DEFAULT_FILTERS, resetForType } from './lib/filter'
import type { Filters, Meta, PropertyType, SearchItem, VisibleItem } from './types'

// 상세 패널은 recharts 를 끌고 오므로 초기 번들에서 분리한다 (NFR: 초기 로딩 < 3초).
const DetailPanel = lazy(() => import('./components/DetailPanel'))

const TABS: { id: PropertyType; label: string; note?: string }[] = [
  { id: 'apt', label: '아파트' },
  { id: 'commercial', label: '상가' },
  { id: 'land', label: '토지' },
  { id: 'auction', label: '경매·공매', note: '현재 온비드 공매만 제공 (법원경매 미포함)' },
]

// 전국 수집이므로 한반도 남부 전체가 보이는 시점에서 시작한다.
const KOREA: [number, number] = [36.2, 127.8]

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [bootError, setBootError] = useState<string | null>(null)

  const [type, setType] = useState<PropertyType>('apt')
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)
  const [view, setView] = useState<ViewState | null>(null)
  const [selected, setSelected] = useState<VisibleItem | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [pendingPick, setPendingPick] = useState<string | null>(null)
  const [flyTo, setFlyTo] = useState<{ lat: number; lng: number; zoom: number; key: number } | null>(null)
  const [mobilePane, setMobilePane] = useState<'map' | 'list'>('map')

  useEffect(() => {
    fetchMeta()
      .then(setMeta)
      .catch((e: Error) => setBootError(e.message))
  }, [])

  const { regions: nation, error: nationError } = useNationSummary(type)
  const { items, loading, pendingRegions, error, auctionFile } = useVisibleData(
    type,
    nation,
    view,
    filters,
  )

  // 검색으로 이동한 뒤, 해당 지역 파일이 로드되면 그때 선택 상태로 승격한다.
  useEffect(() => {
    if (!pendingPick) return
    const hit = items.find((c) => c.id === pendingPick)
    if (hit) {
      setSelected(hit)
      setPendingPick(null)
    }
  }, [items, pendingPick])

  // 필터가 바뀌면 선택된 항목의 통계도 새 필터 기준으로 갱신한다.
  useEffect(() => {
    if (!selected) return
    const fresh = items.find((c) => c.id === selected.id)
    if (fresh && fresh !== selected) setSelected(fresh)
  }, [items, selected])

  const onSelect = useCallback(
    (item: VisibleItem) => {
      setSelected(item)
      track('select_item', { type, name: item.name })
    },
    [type],
  )

  const onPickSearch = useCallback((it: SearchItem) => {
    // 검색 인덱스는 아파트 단지명 기준이다.
    setType('apt')
    setFlyTo({ lat: it.y, lng: it.x, zoom: 16, key: Date.now() })
    setPendingPick(it.i)
    setMobilePane('map')
    track('search_select', { query: it.n })
  }, [])

  const onChangeType = useCallback(
    (next: PropertyType) => {
      setType(next)
      setSelected(null)
      // 가격·면적 조건은 유형마다 단위와 구간이 달라 그대로 넘기면 결과가 0건이 된다.
      setFilters((f) => resetForType(f))
      track('tab_view', { tab: next })
    },
    [],
  )

  const zoomedOut = type !== 'auction' && (!view || view.zoom <= REGION_ZOOM_MAX)

  // 헤더는 '화면에 걸친 시군구'가 아니라 '실제로 목록에 뜬 항목들의 시군구'를 보여준다.
  // 전자는 중심좌표 패딩 때문에 화면 밖 구까지 포함되어 목록과 어긋난다.
  const regionNames = useMemo(() => {
    const counts = new Map<string, number>()
    for (const c of items) counts.set(c.regionName, (counts.get(c.regionName) ?? 0) + 1)
    const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1])
    const shown = ranked.slice(0, 3).map(([name]) => name)
    return ranked.length > 3 ? `${shown.join(', ')} 외 ${ranked.length - 3}곳` : shown.join(', ')
  }, [items])

  const activeTab = TABS.find((t) => t.id === type)

  if (bootError) {
    return (
      <div className="boot-error">
        <h1>데이터를 불러오지 못했습니다</h1>
        <p>{bootError}</p>
        <p className="hint">
          파이프라인이 한 번도 실행되지 않았을 수 있습니다. 로컬에서는{' '}
          <code>python3 -m pipeline.build --mock</code> 로 데이터를 생성하세요.
        </p>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <strong>부동산 통합 모니터링</strong>
          {meta && (
            <span className="asof" title={`생성 ${meta.generatedAt}`}>
              데이터 기준일 {meta.dataAsOf}
              {meta.mock && <em className="mock-tag">모의 데이터</em>}
            </span>
          )}
          {/* hits.sh 무가입 카운터 — 오늘/누적 페이지뷰. 프로덕션 도메인에서만 의미 있음 */}
          {!import.meta.env.DEV && (
            <img
              className="visits-badge"
              src="https://hits.sh/iebkk.github.io/budongsan.svg?view=today-total&label=%EB%B0%A9%EB%AC%B8&color=6b7280&labelColor=374151"
              alt="방문 수 (오늘/누적)"
              title="방문 수 (오늘 / 누적)"
              height={20}
            />
          )}
        </div>
        <SearchBox onPick={onPickSearch} />
      </header>

      <nav className="tabs" aria-label="물건 유형">
        {TABS.map((t) => {
          const ready = meta?.types[t.id] ?? false
          return (
            <button
              key={t.id}
              type="button"
              className={`tab${type === t.id ? ' on' : ''}`}
              disabled={!ready}
              title={ready ? t.note : '이 유형은 아직 수집되지 않았습니다'}
              onClick={() => onChangeType(t.id)}
            >
              {t.label}
              {!ready && <small>준비 중</small>}
            </button>
          )
        })}
      </nav>

      <FilterBar type={type} value={filters} months={meta?.months ?? []} onChange={setFilters} />

      {activeTab?.note && (
        <p className="scope-note" role="note">
          {activeTab.note}
          {auctionFile && auctionFile.outOfScopeCount > 0 && (
            <> · 수집 범위 밖 {auctionFile.outOfScopeCount}건은 제외됨</>
          )}
        </p>
      )}

      <div className={`content pane-${mobilePane}`}>
        <div className="map-wrap">
          <MapView
            center={KOREA}
            zoom={7}
            type={type}
            regions={nation}
            items={items}
            selectedId={selected?.id ?? null}
            hoveredId={hoveredId}
            flyTo={flyTo}
            onViewChange={setView}
            onSelect={onSelect}
            onHover={setHoveredId}
          />
          {(loading || pendingRegions > 0) && <div className="map-loading">데이터 불러오는 중…</div>}
          {(error || nationError) && <div className="map-error">{error ?? nationError}</div>}
        </div>

        <section className="side" aria-label="물건 목록">
          <div className="side-head">
            {zoomedOut ? '전국 시군구 요약' : regionNames || '현재 영역'}
          </div>
          <ListPanel
            type={type}
            items={items}
            loading={loading}
            zoomedOut={zoomedOut}
            selectedId={selected?.id ?? null}
            onSelect={onSelect}
            onHover={setHoveredId}
          />
        </section>

        {selected && (
          <Suspense fallback={<aside className="detail">불러오는 중…</aside>}>
            <DetailPanel item={selected} onClose={() => setSelected(null)} />
          </Suspense>
        )}
      </div>

      <button
        type="button"
        className="pane-toggle"
        onClick={() => setMobilePane(mobilePane === 'map' ? 'list' : 'map')}
      >
        {mobilePane === 'map' ? `목록 ${items.length}` : '지도'}
      </button>

      <footer className="legal">
        본 서비스의 정보는 참고용이며, 거래·입찰 전 원출처(국토교통부, 온비드, 법원) 확인이 필요합니다.
        {meta && <> 출처: {meta.source}</>} 지도 © OpenStreetMap 기여자.
        <br />© 2026 IEBKK. All rights reserved. 사전 서면 허가 없는 복제·수정·재배포·상업적 이용을 금합니다.
      </footer>
    </div>
  )
}
