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
import { fetchMeta, fetchScreener } from './lib/api'
import { track } from './lib/analytics'
import { DEFAULT_FILTERS, resetForType } from './lib/filter'
import type { TabId, Filters, Meta, PropertyType, ScreenerFile, SearchItem, VisibleItem } from './types'

// 상세 패널은 recharts 를 끌고 오므로 초기 번들에서 분리한다 (NFR: 초기 로딩 < 3초).
const DetailPanel = lazy(() => import('./components/DetailPanel'))
const ScreenerPanel = lazy(() => import('./components/ScreenerPanel'))
const CoachPanel = lazy(() => import('./components/CoachPanel'))

const TABS: { id: TabId; label: string; note?: string }[] = [
  { id: 'apt', label: '아파트' },
  { id: 'commercial', label: '상가' },
  { id: 'land', label: '토지' },
  { id: 'auction', label: '경매·공매', note: '현재 온비드 공매만 제공 (법원경매 미포함)' },
  { id: 'screener', label: '수익 스크리너', note: '스크리닝 결과이며 투자 권유가 아닙니다 — 입찰·매수 전 원출처 확인 필수' },
  { id: 'coach', label: '오늘의 코칭', note: '교육용 코칭 콘텐츠이며 투자 권유가 아닙니다 — 판단과 책임은 본인에게 있습니다' },
]

// 전국 수집이므로 한반도 남부 전체가 보이는 시점에서 시작한다.
const KOREA: [number, number] = [36.2, 127.8]

// 첫화면 바로가기 — 탭과 같은 순서, 설명 한 줄씩만.
const HOME_CATS: { id: TabId; label: string; desc: string }[] = [
  { id: 'apt', label: '아파트', desc: '실거래가 지도' },
  { id: 'commercial', label: '상가', desc: '상업·업무용 실거래' },
  { id: 'land', label: '토지', desc: '토지 실거래' },
  { id: 'auction', label: '경매·공매', desc: '온비드 공매 물건' },
  { id: 'screener', label: '수익 스크리너', desc: '급매 · 저평가 · 공매 랭킹' },
  { id: 'coach', label: '오늘의 코칭', desc: '오늘의 1픽 단계별 안내' },
]

// 첫화면 이용 안내 — 처음 방문한 사람이 화면 흐름(검색→지도→상세→랭킹)을 그대로 따라가게.
const HOME_GUIDE: { title: string; body: string }[] = [
  {
    title: '검색하거나 유형 고르기',
    body: '위 검색창에 단지명·지역을 입력하거나, 바로가기 카드에서 아파트·상가·토지·경매공매를 선택하세요.',
  },
  {
    title: '지도에서 둘러보기',
    body: '지도를 움직이고 확대하면 보이는 영역의 물건이 옆 목록에 나타납니다. 기간·가격·면적 필터로 조건을 좁힐 수 있습니다.',
  },
  {
    title: '상세 정보 확인',
    body: '지도 마커나 목록 카드를 누르면 시세 추이 차트와 최근 거래 내역을 볼 수 있습니다.',
  },
  {
    title: '랭킹과 코칭 받기',
    body: '수익 스크리너에서 급매·저평가·공매 랭킹을 확인하고, 오늘의 코칭에서 오늘의 1픽을 단계별로 안내받으세요.',
  },
]

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  // 운영자 접속 제외: ?owner=1 로 한 번 접속하면 그 브라우저는 방문 카운터에서 빠진다.
  // (?owner=0 으로 해제) 집계 요청 자체를 안 보내는 방식.
  const [ownerMode] = useState<boolean>(() => {
    try {
      const q = new URLSearchParams(window.location.search).get('owner')
      if (q === '1') localStorage.setItem('bd_owner', '1')
      if (q === '0') localStorage.removeItem('bd_owner')
      return localStorage.getItem('bd_owner') === '1'
    } catch {
      return false
    }
  })
  // 방문 카운터 (Abacus 무가입 API) — 브라우저마다 하루 1회만 /hit 로 집계하고,
  // 같은 날의 재방문·새로고침은 /get(조회 전용)이라 숫자가 올라가지 않는다.
  const [visits, setVisits] = useState<{ today: number; total: number } | null>(null)
  useEffect(() => {
    if (import.meta.env.DEV || ownerMode) return
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    let counted = true // localStorage 를 못 쓰는 환경이면 집계하지 않는다 (새로고침 중복 방지 우선)
    try {
      counted = localStorage.getItem('bd_visit_date') === today
      if (!counted) localStorage.setItem('bd_visit_date', today)
    } catch {}
    const mode = counted ? 'get' : 'hit'
    const base = 'https://abacus.jasoncameron.dev'
    Promise.all([
      fetch(`${base}/${mode}/iebkk-budongsan/visits`).then((r) => (r.ok ? r.json() : null)),
      fetch(`${base}/${mode}/iebkk-budongsan/visits-${today}`).then((r) => (r.ok ? r.json() : null)),
    ])
      .then(([total, day]) => {
        if (total) setVisits({ today: day?.value ?? 0, total: total.value })
      })
      .catch(() => {})
  }, [ownerMode])
  const [bootError, setBootError] = useState<string | null>(null)

  // 첫화면: 지도 대신 검색창 중심의 심플 랜딩. 검색·바로가기로 진입한다.
  const [home, setHome] = useState(true)
  // 첫화면 시장 요약 카드용 — 오늘의 픽 한 줄을 위해 스크리너를 가볍게 받아둔다(캐시됨).
  const [screener, setScreener] = useState<ScreenerFile | null>(null)
  useEffect(() => {
    if (!home || screener) return
    fetchScreener()
      .then(setScreener)
      .catch(() => {}) // 요약 카드는 부가 정보 — 실패해도 첫화면은 뜬다.
  }, [home, screener])
  const [type, setType] = useState<TabId>('apt')
  // 스크리너·코칭 탭에서는 지도 훅이 아파트 기준으로 대기한다 (화면에는 안 보임)
  const isPanelTab = type === 'screener' || type === 'coach'
  const dataType: PropertyType = isPanelTab ? 'apt' : (type as PropertyType)
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS)
  const [view, setView] = useState<ViewState | null>(null)
  const [selected, setSelected] = useState<VisibleItem | null>(null)
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const [pendingPick, setPendingPick] = useState<string | null>(null)
  const [flyTo, setFlyTo] = useState<{ lat: number; lng: number; zoom: number; key: number } | null>(null)
  const [highlight, setHighlight] = useState<{ lat: number; lng: number; label: string; key: number } | null>(null)
  const [mobilePane, setMobilePane] = useState<'map' | 'list'>('map')

  useEffect(() => {
    fetchMeta()
      .then(setMeta)
      .catch((e: Error) => setBootError(e.message))
  }, [])

  const { regions: nation, error: nationError } = useNationSummary(dataType)
  const { items, loading, pendingRegions, error, auctionFile } = useVisibleData(
    dataType,
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
    setHome(false)
    setType('apt')
    setFlyTo({ lat: it.y, lng: it.x, zoom: 16, key: Date.now() })
    setPendingPick(it.i)
    setMobilePane('map')
    track('search_select', { query: it.n })
  }, [])

  // 스크리너 행 클릭 → 해당 유형 탭으로 전환하고 지도를 그 위치로 보낸다.
  const onLocateFromScreener = useCallback(
    (lat: number, lng: number, tab: PropertyType, label?: string) => {
      setType(tab)
      setSelected(null)
      setFilters((f) => resetForType(f))
      setFlyTo({ lat, lng, zoom: 16, key: Date.now() })
      // 추천 상세에서 넘어온 경우 그 물건을 전용 색 마커로 강조한다.
      setHighlight(label ? { lat, lng, label, key: Date.now() } : null)
      setMobilePane('map')
      track('screener_locate', { tab })
    },
    [],
  )

  const onChangeType = useCallback(
    (next: TabId) => {
      setType(next)
      setSelected(null)
      setHighlight(null) // 탭을 직접 바꾸면 추천 강조 해제
      // 가격·면적 조건은 유형마다 단위와 구간이 달라 그대로 넘기면 결과가 0건이 된다.
      setFilters((f) => resetForType(f))
      track('tab_view', { tab: next })
    },
    [],
  )

  // 첫화면 바로가기 → 해당 탭으로 진입
  const onEnterTab = useCallback(
    (next: TabId) => {
      setHome(false)
      onChangeType(next)
      track('home_shortcut', { tab: next })
    },
    [onChangeType],
  )

  const goHome = useCallback(() => {
    setHome(true)
    setSelected(null)
    setHighlight(null)
    track('home_return')
  }, [])

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

  const legalFooter = (
    <footer className="legal">
      본 서비스의 정보는 참고용이며, 거래·입찰 전 원출처(국토교통부, 온비드, 법원) 확인이 필요합니다.
      {meta && <> 출처: {meta.source}</>} 지도 © OpenStreetMap 기여자.
      <br />© 2026 IEBKK. All rights reserved. 사전 서면 허가 없는 복제·수정·재배포·상업적 이용을 금합니다.{' '}
      <a href={`${import.meta.env.BASE_URL}privacy.html`}>개인정보처리방침</a>
    </footer>
  )

  if (home) {
    const countOf = (id: TabId): number | null => {
      if (id === 'auction') return meta?.auction?.count ?? null
      if (id === 'apt' || id === 'commercial' || id === 'land')
        return meta?.dealCountByType[id] ?? null
      return null
    }
    const num = (n?: number | null) => (n ?? 0).toLocaleString()
    // 요약 카드의 오늘의 픽: 코칭이 고른 1픽 우선, 없으면 첫 추천.
    const pick =
      screener?.dailyPicks?.find((p) => p.kind === screener.coach?.pickKind) ??
      screener?.dailyPicks?.[0] ??
      null
    return (
      <div className="app home">
        <main className="home-hero">
          <h1 className="home-title">부동산 통합 모니터링</h1>
          <p className="home-sub">
            전국 {meta ? meta.regionCount : 256}개 시군구의 아파트·상가·토지 실거래가와 온비드
            공매 물건을 지도 한 곳에서 확인하는 서비스입니다.
            {meta?.mock && <em className="mock-tag">모의 데이터</em>}
          </p>
          <ul className="home-features" aria-label="서비스 특징">
            <li>국토교통부 실거래가</li>
            <li>온비드 공매</li>
            <li>수익 스크리너 · 코칭</li>
            <li>매일 자동 갱신{meta && <> · {meta.dataAsOf}</>}</li>
          </ul>
          <SearchBox hero onPick={onPickSearch} />
          {meta && (
            <section className="home-brief" aria-label="오늘의 시장 요약">
              <div className="brief-head">
                <span className="brief-kicker">Market Brief</span>
                <span className="brief-date">최근 3개월 · {meta.dataAsOf} 기준</span>
              </div>
              <div className="brief-stats">
                <div>
                  <b>{num(meta.dealCountByType.apt)}</b>
                  <span>아파트 거래</span>
                </div>
                <div>
                  <b>{num(meta.dealCountByType.commercial)}</b>
                  <span>상가 거래</span>
                </div>
                <div>
                  <b>{num(meta.dealCountByType.land)}</b>
                  <span>토지 거래</span>
                </div>
                <div>
                  <b>{num(meta.auction?.count)}</b>
                  <span>
                    공매 물건
                    {meta.auction?.avgBidRate != null && <> · 평균 최저가율 {Math.round(meta.auction.avgBidRate)}%</>}
                  </span>
                </div>
              </div>
              {pick && (
                <button type="button" className="brief-pick" onClick={() => onEnterTab('coach')}>
                  <span className="pick-label">오늘의 픽</span>
                  <span className="pick-body">
                    <b>{pick.title}</b>
                    <i>{pick.headline}</i>
                  </span>
                  <span className="pick-go">코칭 보기 →</span>
                </button>
              )}
            </section>
          )}
          <nav className="home-cats" aria-label="바로가기">
            {HOME_CATS.map((c) => {
              const ready =
                c.id === 'screener' || c.id === 'coach'
                  ? Boolean(meta?.types.apt && meta?.types.auction)
                  : (meta?.types[c.id] ?? false)
              const n = countOf(c.id)
              return (
                <button
                  key={c.id}
                  type="button"
                  className="cat-card"
                  disabled={!ready}
                  onClick={() => onEnterTab(c.id)}
                >
                  <b>{c.label}</b>
                  <span>{c.desc}</span>
                  {n !== null && <small>{n.toLocaleString()}건</small>}
                </button>
              )
            })}
          </nav>
          <section className="home-guide" aria-label="이용 방법">
            <h2>처음이신가요? 이렇게 이용하세요</h2>
            <ol className="guide-steps">
              {HOME_GUIDE.map((g, i) => (
                <li key={g.title} className="guide-step">
                  <span className="guide-no" aria-hidden>
                    {i + 1}
                  </span>
                  <div>
                    <b>{g.title}</b>
                    <p>{g.body}</p>
                  </div>
                </li>
              ))}
            </ol>
            <p className="guide-note">
              모든 정보는 공공데이터(국토교통부 실거래가, 온비드 공매)를 매일 자동 수집해
              제공하며, 참고용입니다. 입찰·매수 전 반드시 원출처를 확인하세요.
            </p>
          </section>
          {(visits || ownerMode) && (
            <p className="home-visits">
              {visits && <>방문 {visits.today.toLocaleString()} / 누적 {visits.total.toLocaleString()}</>}
              {ownerMode && <span className="owner-tag" title="이 브라우저의 접속은 방문 수에 집계되지 않습니다. 해제: 주소에 ?owner=0">집계 제외 중</span>}
            </p>
          )}
        </main>
        {legalFooter}
      </div>
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <button type="button" className="brand-home" onClick={goHome} title="첫화면으로 돌아가기">
            <span className="home-ico" aria-hidden>⌂</span>
            <strong>부동산 통합 모니터링</strong>
          </button>
          {meta && (
            <span className="asof" title={`생성 ${meta.generatedAt}`}>
              데이터 기준일 {meta.dataAsOf}
              {meta.mock && <em className="mock-tag">모의 데이터</em>}
            </span>
          )}
          {ownerMode && (
            <span className="owner-tag" title="이 브라우저의 접속은 방문 수에 집계되지 않습니다. 해제: 주소에 ?owner=0">
              집계 제외 중
            </span>
          )}
          {visits && (
            <span className="visits-badge" title="방문 수 (오늘 / 누적) — 브라우저당 하루 1회 집계">
              방문 {visits.today.toLocaleString()} / {visits.total.toLocaleString()}
            </span>
          )}
        </div>
        <SearchBox onPick={onPickSearch} />
      </header>

      <nav className="tabs" aria-label="물건 유형">
        {TABS.map((t) => {
          const ready =
            t.id === 'screener' || t.id === 'coach'
              ? Boolean(meta?.types.apt && meta?.types.auction)
              : (meta?.types[t.id] ?? false)
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

      {!isPanelTab && (
        <FilterBar type={dataType} value={filters} months={meta?.months ?? []} onChange={setFilters} />
      )}

      {activeTab?.note && (
        <p className="scope-note" role="note">
          {activeTab.note}
          {auctionFile && auctionFile.outOfScopeCount > 0 && (
            <> · 수집 범위 밖 {auctionFile.outOfScopeCount}건은 제외됨</>
          )}
        </p>
      )}

      {type === 'screener' ? (
        <Suspense fallback={<div className="screener"><p className="scr-loading">스크리너 불러오는 중…</p></div>}>
          <ScreenerPanel onLocate={onLocateFromScreener} />
        </Suspense>
      ) : type === 'coach' ? (
        <Suspense fallback={<div className="coach"><p className="scr-loading">오늘의 코칭 불러오는 중…</p></div>}>
          <CoachPanel onLocate={onLocateFromScreener} />
        </Suspense>
      ) : (
      <div className={`content pane-${mobilePane}`}>
        <div className="map-wrap">
          <MapView
            center={KOREA}
            zoom={7}
            type={dataType}
            regions={nation}
            items={items}
            selectedId={selected?.id ?? null}
            hoveredId={hoveredId}
            flyTo={flyTo}
            highlight={highlight}
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
            type={dataType}
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
      )}

      {!isPanelTab && (
      <button
        type="button"
        className="pane-toggle"
        onClick={() => setMobilePane(mobilePane === 'map' ? 'list' : 'map')}
      >
        {mobilePane === 'map' ? `목록 ${items.length}` : '지도'}
      </button>
      )}

      {legalFooter}
    </div>
  )
}
