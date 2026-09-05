import { useEffect, useState } from 'react'
import type { PropertyType, TradeType, ScreenerFile, ScreenerAuctionRow, ScreenerUrgentRow } from '../types'
import { fetchScreener } from '../lib/api'

function eok(man: number): string {
  return man >= 10000 ? `${(man / 10000).toFixed(2)}억` : `${man.toLocaleString()}만`
}

function chipClass(tag: string): string {
  if (tag.includes('강력') || tag.includes('문제물건') || tag.includes('괴리') || tag.includes('특수거래'))
    return 'rtag risk'
  if (tag.includes('수의계약')) return 'rtag ok'
  if (tag.includes('압류재산') || tag.includes('표본') || tag.includes('유의') || tag.includes('가능성'))
    return 'rtag note'
  return 'rtag warn'
}

function Tags({ tags }: { tags: string[] }) {
  if (!tags.length) return <span className="rtag ok">특이사항 없음</span>
  return (
    <>
      {tags.map((t) => (
        <span key={t} className={chipClass(t)}>
          {t}
        </span>
      ))}
    </>
  )
}

const KIND_FILTERS = [
  { id: 'all', label: '전체' },
  { id: 'apt', label: '아파트' },
  { id: 'commercial', label: '상가' },
  { id: 'land', label: '토지' },
] as const

export default function ScreenerPanel({
  onLocate,
}: {
  onLocate: (lat: number, lng: number, tab: PropertyType) => void
}) {
  const [data, setData] = useState<ScreenerFile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [urgentKind, setUrgentKind] = useState<string>('all')

  useEffect(() => {
    fetchScreener().then(setData).catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <div className="screener"><p className="scr-error">{error}</p></div>
  if (!data) return <div className="screener"><p className="scr-loading">스크리너 계산 결과 불러오는 중…</p></div>

  const urgent = data.urgent.filter((u) => urgentKind === 'all' || u.kind === urgentKind)

  return (
    <div className="screener">
      <div className="scr-stats">
        <div><b>{data.urgentTotal.toLocaleString()}</b><span>급매·이상 저가 신호</span></div>
        <div><b>{data.auctionEligible.toLocaleString()}</b><span>공매 적격 (매각·입찰가능)</span></div>
        <div><b>{data.auctionTop.length}</b><span>공매 추천 TOP</span></div>
        <div><b>{data.generatedAt}</b><span>계산 기준일</span></div>
      </div>

      <section className="scr-section">
        <div className="scr-head">
          <h2>급매 · 이상 저가 거래 신호</h2>
          <div className="scr-kinds" role="group" aria-label="유형 필터">
            {KIND_FILTERS.map((k) => (
              <button
                key={k.id}
                type="button"
                className={urgentKind === k.id ? 'on' : ''}
                onClick={() => setUrgentKind(k.id)}
              >
                {k.label}
                {k.id !== 'all' && data.urgentByKind[k.id as TradeType] != null && (
                  <small> {data.urgentByKind[k.id as TradeType]}</small>
                )}
              </button>
            ))}
          </div>
        </div>
        <p className="scr-note">
          같은 단지·면적대(아파트) 또는 같은 물건 내 단가(상가·토지) 기준으로 시세 대비 크게 싸게
          신고된 거래입니다. 아파트 −40% 이하는 직거래·증여성 이전일 가능성이 높습니다.
        </p>
        <div className="scr-tblwrap">
          <table>
            <thead>
              <tr><th>유형</th><th>낙폭</th><th>물건 / 위치</th><th>거래가</th><th>시세 기준</th><th>거래일</th><th>확인 필요</th></tr>
            </thead>
            <tbody>
              {urgent.slice(0, 30).map((u: ScreenerUrgentRow, i) => (
                <tr key={`${u.complex}-${u.dealtAt}-${i}`} onClick={() => onLocate(u.lat, u.lng, u.kind as PropertyType)}>
                  <td>{u.kindLabel}</td>
                  <td className="drop">{u.drop.toFixed(1)}%</td>
                  <td className="name">
                    {u.complex}
                    <div className="sub">
                      {u.region} {u.umd} · {u.area}㎡{u.floor != null ? ` ${u.floor}층` : ''}
                    </div>
                  </td>
                  <td className="num">{eok(u.amount)}</td>
                  <td className="num">{eok(u.median)}</td>
                  <td className="num">{u.dealtAt}</td>
                  <td className="tags"><Tags tags={u.tags} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="scr-section">
        <div className="scr-head"><h2>공매 수익 랭킹 TOP {data.auctionTop.length}</h2></div>
        <p className="scr-note">
          점수 = 할인 폭 × 동네 유동성 × 리스크 보정. 유찰로 할인이 &lsquo;정당하게 벌어진&rsquo;
          물건이 위로 오고, 유찰 없이 극단적으로 싼 물건(지분·특수물건 신호)과 유찰 10회 이상
          장기 미매각은 감점됩니다. 같은 건물 여러 호실은 대표 1건으로 묶었습니다.
        </p>
        <div className="scr-tblwrap">
          <table>
            <thead>
              <tr><th>점수</th><th>물건 / 위치</th><th>최저입찰</th><th>감정가</th><th>최저가율</th><th>유찰</th><th>동네 거래</th><th>마감</th><th>리스크</th></tr>
            </thead>
            <tbody>
              {data.auctionTop.map((s: ScreenerAuctionRow) => (
                <tr key={s.id} onClick={() => onLocate(s.lat, s.lng, 'auction')}>
                  <td className="score">{Math.round(s.score)}</td>
                  <td className="name">
                    {s.name}
                    {s.bundle > 1 && <span className="bundle"> 외 {s.bundle - 1}건</span>}
                    <div className="sub">
                      {s.region} {s.umd} · {s.category} · 관리번호 {s.mgmtNo}
                    </div>
                  </td>
                  <td className="num">{eok(s.minBid)}</td>
                  <td className="num">{eok(s.appraisal)}</td>
                  <td className="num">{Math.round(s.bidRate)}%</td>
                  <td className="num">{s.failCount}회</td>
                  <td className="num">{s.liquidity}건</td>
                  <td className="num">
                    {s.closeAt}
                    {s.days != null && s.days >= 0 && <span className="dday"> D-{s.days}</span>}
                  </td>
                  <td className="tags"><Tags tags={s.tags} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <p className="scr-caveat">
        ⚠ 스크리닝 결과이며 투자 권유가 아닙니다. 공매는 입찰 전 온비드 원문 공고에서
        권리관계(임차인·유치권·지분)와 명도 조건을 반드시 확인하세요. 행을 클릭하면 지도로
        이동합니다(경매·공매 탭에서 상세 확인).
      </p>
    </div>
  )
}
