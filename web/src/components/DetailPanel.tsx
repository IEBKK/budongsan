import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  formatAmount,
  formatDate,
  formatDaysToClose,
  formatIsoDate,
  formatPpp,
  formatYm,
  pyeong,
  shortCategory,
} from '../lib/format'
import { CLOSING_SOON_DAYS } from '../lib/filter'
import { isAuction, type VisibleAuction, type VisibleItem, type VisibleTrade } from '../types'

interface Props {
  item: VisibleItem
  onClose: () => void
}

const AREA_LABEL: Record<string, string> = {
  apt: '전용면적',
  commercial: '건물면적',
  land: '거래면적',
}

function TradeDetail({ item }: { item: VisibleTrade }) {
  const [areaFilter, setAreaFilter] = useState<string | null>(null)

  const deals = useMemo(() => {
    // 면적 칩은 유형에 따라 실면적(아파트) 또는 구간(상가·토지)을 뜻한다.
    const bucket = item.areas.find((a) => a.label === areaFilter)
    const list =
      areaFilter && bucket
        ? item.kind === 'apt'
          ? item.deals.filter((d) => Math.abs(d.area - bucket.areaM2) < 0.005)
          : item.deals.filter((d) => {
              const py = d.area / 3.3058
              const bounds = BUCKET_BOUNDS[bucket.label]
              return bounds ? py >= bounds[0] && py < bounds[1] : true
            })
        : item.deals
    return [...list].sort((a, b) =>
      (b.ym + String(b.day).padStart(2, '0')).localeCompare(a.ym + String(a.day).padStart(2, '0')),
    )
  }, [item, areaFilter])

  const chart = useMemo(
    () => item.series.map((p) => ({ ...p, label: formatYm(p.ym) })),
    [item.series],
  )
  const meta = item.extra

  return (
    <>
      <div className="stat-row">
        <div className="stat">
          <span>중위 실거래가</span>
          <b>{formatAmount(item.filteredMedian)}</b>
        </div>
        <div className="stat">
          <span>평단가</span>
          <b>{formatPpp(item.filteredPpp)}</b>
        </div>
        <div className="stat">
          <span>거래 건수</span>
          <b>{item.filteredCount}건</b>
        </div>
      </div>

      {(meta.use || meta.jimok || meta.landUse || meta.buildingType) && (
        <div className="fact-row">
          {meta.use && <span><i>용도</i>{meta.use}</span>}
          {meta.jimok && <span><i>지목</i>{meta.jimok}</span>}
          {meta.buildingType && <span><i>유형</i>{meta.buildingType}</span>}
          {meta.landUse && <span><i>용도지역</i>{meta.landUse}</span>}
          {meta.plottageAr ? <span><i>대지면적</i>{meta.plottageAr}㎡</span> : null}
        </div>
      )}

      <section>
        <h3>평단가 추이</h3>
        {chart.length > 1 ? (
          <div className="chart">
            <ResponsiveContainer width="100%" height={160}>
              <LineChart data={chart} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#eceef1" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
                <YAxis
                  width={52}
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(v: number) => `${Math.round(v / 100) / 10}천`}
                  domain={['dataMin - 200', 'dataMax + 200']}
                />
                <Tooltip
                  formatter={(v: number) => [formatPpp(v), '평단가']}
                  labelFormatter={(l: string) => `20${l}`}
                />
                <Line type="monotone" dataKey="pricePerPyeong" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="hint">추이를 그리기에 거래 개월 수가 부족합니다.</p>
        )}
      </section>

      <section>
        <h3>{item.kind === 'apt' ? '면적 타입' : '면적 구간'}</h3>
        <div className="chips">
          <button
            type="button"
            className={`chip${areaFilter === null ? ' on' : ''}`}
            onClick={() => setAreaFilter(null)}
          >
            전체
          </button>
          {item.areas.map((a) => (
            <button
              key={a.label}
              type="button"
              className={`chip${areaFilter === a.label ? ' on' : ''}`}
              onClick={() => setAreaFilter(areaFilter === a.label ? null : a.label)}
              title={`${a.count}건 · 중위 ${formatAmount(a.medianAmount)}`}
            >
              {item.kind === 'apt' ? `${pyeong(a.areaM2)}평` : a.label} <small>{a.count}</small>
            </button>
          ))}
        </div>
      </section>

      <section>
        <h3>최근 거래 ({deals.length}건)</h3>
        <div className="table-scroll">
          <table className="deals">
            <thead>
              <tr>
                <th>계약일</th>
                <th>{AREA_LABEL[item.kind]}</th>
                {item.kind === 'land' ? <th>구분</th> : <th>층</th>}
                <th className="num">거래가</th>
              </tr>
            </thead>
            <tbody>
              {deals.map((d, i) => (
                <tr key={`${d.ym}-${d.day}-${d.area}-${d.floor}-${i}`}>
                  <td>{formatDate(d.ym, d.day)}</td>
                  <td>{d.area}㎡</td>
                  <td>{item.kind === 'land' ? d.share || '일반' : d.floor ?? '-'}</td>
                  <td className="num">{formatAmount(d.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {item.dealCount > item.deals.length && (
          <p className="hint">항목당 최근 {item.deals.length}건까지 제공됩니다.</p>
        )}
      </section>
    </>
  )
}

// transform.py 의 _PYEONG_BUCKETS 와 같은 경계
const BUCKET_BOUNDS: Record<string, [number, number]> = {
  '10평 미만': [0, 10],
  '10~30평': [10, 30],
  '30~100평': [30, 100],
  '100~300평': [100, 300],
  '300평 이상': [300, Infinity],
}

function AuctionDetail({ item }: { item: VisibleAuction }) {
  const closing =
    item.daysToClose !== null && item.daysToClose >= 0 && item.daysToClose <= CLOSING_SOON_DAYS
  const discount = item.appraisal > 0 ? item.appraisal - item.minBid : 0

  return (
    <>
      <div className="stat-row">
        <div className="stat">
          <span>최저입찰가</span>
          <b>{formatAmount(item.minBid)}</b>
        </div>
        <div className="stat">
          <span>감정가</span>
          <b>{item.appraisal > 0 ? formatAmount(item.appraisal) : '-'}</b>
        </div>
        <div className="stat">
          <span>최저가율</span>
          <b>{item.bidRate !== null ? `${item.bidRate.toFixed(0)}%` : '-'}</b>
        </div>
      </div>

      {discount > 0 && (
        <p className="callout">
          감정가 대비 <b>{formatAmount(discount)}</b> 낮음
          {item.failCount > 0 && ` · ${item.failCount}회 유찰 누적`}
        </p>
      )}

      <section>
        <h3>입찰 일정</h3>
        <div className="fact-row col">
          <span>
            <i>시작</i>
            {formatIsoDate(item.beginAt)}
          </span>
          <span className={closing ? 'closing' : undefined}>
            <i>마감</i>
            {formatIsoDate(item.closeAt)} ({formatDaysToClose(item.daysToClose)})
          </span>
          <span>
            <i>상태</i>
            {item.status || '-'}
          </span>
          <span>
            <i>입찰방식</i>
            {[item.disposal, item.bidMethod].filter(Boolean).join(' · ') || '-'}
          </span>
        </div>
      </section>

      <section>
        <h3>물건 정보</h3>
        <div className="fact-row col">
          <span>
            <i>종류</i>
            {shortCategory(item.category)}
          </span>
          <span>
            <i>소재지</i>
            {item.address}
          </span>
          {item.extra.roadAddress && (
            <span>
              <i>도로명</i>
              {item.extra.roadAddress}
            </span>
          )}
          <span>
            <i>집행기관</i>
            {item.institution || '한국자산관리공사'}
          </span>
          {item.extra.mgmtNo && (
            <span>
              <i>관리번호</i>
              {item.extra.mgmtNo}
            </span>
          )}
          {(item.roundCount ?? 1) > 1 && (
            <span>
              <i>공고 회차</i>
              {item.roundCount}건 중 대표 회차 표시
            </span>
          )}
          <span>
            <i>최초 관측</i>
            {item.firstSeen}
          </span>
        </div>
      </section>

      <p className="hint">
        온비드 공매 물건입니다(법원경매 아님). 입찰 전 온비드 원문 공고에서 권리관계·명도 조건을 반드시
        확인하세요.
      </p>
    </>
  )
}

export default function DetailPanel({ item, onClose }: Props) {
  const auction = isAuction(item)
  return (
    <aside className="detail" aria-label={`${item.name} 상세`}>
      <header className="detail-head">
        <div>
          <h2>{item.name}</h2>
          <p className="detail-addr">
            {auction
              ? `${item.regionName} ${item.umd} · ${shortCategory(item.category)}`
              : `${item.regionName} ${item.umd} ${item.jibun}${
                  item.buildYear ? ` · ${item.buildYear}년 준공` : ''
                }`}
          </p>
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="상세 닫기">
          ✕
        </button>
      </header>

      {auction ? <AuctionDetail item={item} /> : <TradeDetail item={item} />}
    </aside>
  )
}
