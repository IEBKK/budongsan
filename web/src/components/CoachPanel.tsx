import { useEffect, useState } from 'react'
import type { CoachStep, PickComps, PropertyType, ScreenerFile } from '../types'
import { fetchScreener } from '../lib/api'

// 오늘의 코칭 — 추천 후보 중 1픽을 부동산 코치가 옆에서 안내하듯 단계별로 보여준다.
// 문장·플랜은 파이프라인(screener.py)이 데이터에서 생성하고, 여기서는 배치만 담당한다.
export default function CoachPanel({
  onLocate,
}: {
  onLocate: (lat: number, lng: number, tab: PropertyType, label?: string) => void
}) {
  const [data, setData] = useState<ScreenerFile | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchScreener().then(setData).catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <div className="coach"><p className="scr-error">{error}</p></div>
  if (!data) return <div className="coach"><p className="scr-loading">오늘의 코칭 불러오는 중…</p></div>

  const coach = data.coach
  const pick = coach ? data.dailyPicks?.find((p) => p.kind === coach.pickKind) : undefined
  if (!coach || !pick || !pick.analysis) {
    return (
      <div className="coach">
        <p className="scr-loading">오늘의 코칭이 아직 준비되지 않았습니다 — 다음 데이터 갱신 때 생성됩니다.</p>
      </div>
    )
  }
  const a = pick.analysis

  const widget = (step: CoachStep) => {
    switch (step.widget) {
      case 'metrics':
        return (
          <div className="coach-metrics">
            {pick.metrics.map(([k, v]) => (
              <div key={k}>
                <i>{k}</i>
                <b>{v}</b>
              </div>
            ))}
            <div>
              <i>{pick.kind === 'auction' ? '점수' : '할인 폭'}</i>
              <b className="coach-headline-num">{pick.headline}</b>
            </div>
          </div>
        )
      case 'comps':
        return a.comps ? <CompsTable comps={a.comps} /> : null
      case 'funding':
        return a.profit ? (
          <dl className="pick-evidence coach-costs">
            {a.profit.costs.map(([k, v]) => (
              <div key={k} className={k.startsWith('총 투입') ? 'total' : ''}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
        ) : null
      case 'scenarios':
        return a.profit ? (
          <>
            <div className="scr-tblwrap">
              <table className="pick-profit">
                <thead>
                  <tr><th>시나리오</th><th>매도 가정</th><th>세전 차익</th><th>수익률</th></tr>
                </thead>
                <tbody>
                  {a.profit.scenarios.map(([label, sell, net, roi], i) => (
                    <tr key={label} className={i === 1 ? 'baseline' : ''}>
                      <td>{label}{i === 1 && <span className="baseline-tag">판단 기준</span>}</td>
                      <td>{sell}</td>
                      <td className={net.startsWith('−') || net.startsWith('-') ? 'neg' : 'pos'}>{net}</td>
                      <td className={roi.startsWith('-') ? 'neg' : 'pos'}>{roi}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="pick-assume">
              {a.profit.assumptions.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </>
        ) : null
      case 'risks':
        return a.risks && a.risks.length > 0 ? (
          <div className="pick-risks">
            {[...a.risks]
              .sort((x, y) => rank(x[1]) - rank(y[1]))
              .map(([name, level, desc]) => (
                <div key={name}>
                  <span className={`rlevel ${level === '높음' ? 'risk' : level === '중간' ? 'warn' : 'ok'}`}>
                    {level}
                  </span>
                  <div>
                    <b>{name}</b>
                    <p>{desc}</p>
                  </div>
                </div>
              ))}
          </div>
        ) : null
      case 'plan':
        return (
          <ol className="coach-plan">
            {coach.plan.map(([when, what]) => (
              <li key={when}>
                <b>{when}</b>
                <span>{what}</span>
              </li>
            ))}
          </ol>
        )
      default:
        return null
    }
  }

  return (
    <div className="coach">
      <div className="coach-inner">
        <header className="coach-hero">
          <div className="coach-hero-top">
            <span className={`pick-kind k-${pick.kind}`}>{coach.headline}</span>
            <span className="coach-date">기준일 {coach.date}</span>
          </div>
          <h2>{pick.title}</h2>
          <p className="pick-sub">{pick.sub}</p>
          <div className="coach-intro">
            {coach.intro.map((s) => (
              <p key={s}>{s}</p>
            ))}
          </div>
          <div className="coach-hero-actions">
            <button
              type="button"
              className="pick-go"
              onClick={() => onLocate(pick.lat, pick.lng, pick.tab, pick.title)}
            >
              지도에서 보기
            </button>
          </div>
        </header>

        {coach.steps.map((step, i) => (
          <section key={step.title} className="coach-step">
            <div className="coach-step-head">
              <span className="coach-no">{i + 1}</span>
              <h3>{step.title}</h3>
            </div>
            {step.body.map((s) => (
              <p key={s} className="coach-body">{s}</p>
            ))}
            {widget(step)}
            {step.point && (
              <blockquote className="coach-point">
                <i>코치 포인트</i>
                {step.point}
              </blockquote>
            )}
          </section>
        ))}

        <section className="coach-step">
          <div className="coach-step-head">
            <span className="coach-no">{coach.steps.length + 1}</span>
            <h3>마지막 점검 — 이 목록이 다 지워졌을 때만</h3>
          </div>
          <ul className="pick-checklist">
            {a.checklist.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </section>

        <p className="scr-caveat">
          ⚠ 본 코칭은 공개 데이터 기반의 교육용 콘텐츠이며 투자 권유가 아닙니다. 모든 수치는
          세전 근사치이고, 실제 세금·비용은 물건과 매수인 조건에 따라 달라집니다. 거래·입찰의
          판단과 책임은 본인에게 있습니다.
        </p>
      </div>
    </div>
  )
}

function rank(level: string): number {
  return level === '높음' ? 0 : level === '중간' ? 1 : 2
}

export function CompsTable({ comps }: { comps: PickComps }) {
  return (
    <div className="scr-tblwrap">
      <table className="pick-profit comps">
        <caption className="comps-caption">{comps.title}</caption>
        <thead>
          <tr>
            {comps.headers.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {comps.rows.map((r, i) => (
            <tr key={i} className={r[r.length - 1] === '이번 거래' ? 'this-deal' : ''}>
              {r.map((c, j) => (
                <td key={j}>{c === '이번 거래' ? <span className="this-deal-tag">이번 거래</span> : c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
