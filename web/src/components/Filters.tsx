import type { AuctionStatusFilter, Filters, PropertyType } from '../types'

interface Props {
  type: PropertyType
  value: Filters
  months: string[]
  onChange: (next: Filters) => void
}

const PERIODS = [1, 3, 6, 12]

type Range = { label: string; min: number | null; max: number | null }

// 만원 단위. 유형마다 가격대가 크게 달라 구간을 따로 둔다.
const PRICE_RANGES: Record<PropertyType, Range[]> = {
  apt: [
    { label: '전체 가격', min: null, max: null },
    { label: '~ 5억', min: null, max: 50000 },
    { label: '5 ~ 10억', min: 50000, max: 100000 },
    { label: '10 ~ 20억', min: 100000, max: 200000 },
    { label: '20억 ~', min: 200000, max: null },
  ],
  commercial: [
    { label: '전체 가격', min: null, max: null },
    { label: '~ 3억', min: null, max: 30000 },
    { label: '3 ~ 10억', min: 30000, max: 100000 },
    { label: '10 ~ 50억', min: 100000, max: 500000 },
    { label: '50억 ~', min: 500000, max: null },
  ],
  land: [
    { label: '전체 가격', min: null, max: null },
    { label: '~ 1억', min: null, max: 10000 },
    { label: '1 ~ 5억', min: 10000, max: 50000 },
    { label: '5 ~ 20억', min: 50000, max: 200000 },
    { label: '20억 ~', min: 200000, max: null },
  ],
  auction: [
    { label: '전체 최저가', min: null, max: null },
    { label: '~ 1억', min: null, max: 10000 },
    { label: '1 ~ 5억', min: 10000, max: 50000 },
    { label: '5 ~ 15억', min: 50000, max: 150000 },
    { label: '15억 ~', min: 150000, max: null },
  ],
}

// 전용/건물/거래 면적 m2
const AREA_RANGES: Record<Exclude<PropertyType, 'auction'>, Range[]> = {
  apt: [
    { label: '전체 면적', min: null, max: null },
    { label: '~ 60㎡', min: null, max: 60 },
    { label: '60 ~ 85㎡', min: 60, max: 85 },
    { label: '85 ~ 135㎡', min: 85, max: 135 },
    { label: '135㎡ ~', min: 135, max: null },
  ],
  commercial: [
    { label: '전체 면적', min: null, max: null },
    { label: '~ 100㎡', min: null, max: 100 },
    { label: '100 ~ 330㎡', min: 100, max: 330 },
    { label: '330 ~ 1,000㎡', min: 330, max: 1000 },
    { label: '1,000㎡ ~', min: 1000, max: null },
  ],
  land: [
    { label: '전체 면적', min: null, max: null },
    { label: '~ 200㎡', min: null, max: 200 },
    { label: '200 ~ 660㎡', min: 200, max: 660 },
    { label: '660 ~ 2,000㎡', min: 660, max: 2000 },
    { label: '2,000㎡ ~', min: 2000, max: null },
  ],
}

const BID_RATES: { label: string; max: number | null }[] = [
  { label: '전체 최저가율', max: null },
  { label: '감정가 50% 이하', max: 50 },
  { label: '감정가 70% 이하', max: 70 },
  { label: '감정가 90% 이하', max: 90 },
]

const FAIL_COUNTS: { label: string; min: number | null }[] = [
  { label: '유찰 무관', min: null },
  { label: '1회 이상 유찰', min: 1 },
  { label: '2회 이상 유찰', min: 2 },
  { label: '3회 이상 유찰', min: 3 },
]

const STATUSES: { label: string; value: AuctionStatusFilter }[] = [
  { label: '전체', value: 'all' },
  { label: '신규(NEW)', value: 'new' },
  { label: '마감 임박', value: 'closing' },
]

function indexOfRange(ranges: Range[], min: number | null, max: number | null) {
  const i = ranges.findIndex((r) => r.min === min && r.max === max)
  return i < 0 ? 0 : i
}

export default function FilterBar({ type, value, months, onChange }: Props) {
  const prices = PRICE_RANGES[type]

  if (type === 'auction') {
    return (
      <div className="filters">
        <label>
          <span>상태</span>
          <select
            value={value.auctionStatus}
            onChange={(e) => onChange({ ...value, auctionStatus: e.target.value as AuctionStatusFilter })}
          >
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>최저가</span>
          <select
            value={indexOfRange(prices, value.minAmount, value.maxAmount)}
            onChange={(e) => {
              const r = prices[Number(e.target.value)]
              onChange({ ...value, minAmount: r.min, maxAmount: r.max })
            }}
          >
            {prices.map((p, i) => (
              <option key={p.label} value={i}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>최저가율</span>
          <select
            value={BID_RATES.findIndex((r) => r.max === value.maxBidRate)}
            onChange={(e) => onChange({ ...value, maxBidRate: BID_RATES[Number(e.target.value)].max })}
          >
            {BID_RATES.map((r, i) => (
              <option key={r.label} value={i}>
                {r.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>유찰</span>
          <select
            value={FAIL_COUNTS.findIndex((r) => r.min === value.minFailCount)}
            onChange={(e) => onChange({ ...value, minFailCount: FAIL_COUNTS[Number(e.target.value)].min })}
          >
            {FAIL_COUNTS.map((r, i) => (
              <option key={r.label} value={i}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
      </div>
    )
  }

  const areas = AREA_RANGES[type]
  const available = months.length

  return (
    <div className="filters">
      <label>
        <span>기간</span>
        <select
          value={value.months}
          onChange={(e) => onChange({ ...value, months: Number(e.target.value) })}
        >
          {PERIODS.map((m) => (
            <option key={m} value={m}>
              최근 {m}개월{m > available ? ` (수집 ${available}개월)` : ''}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span>가격</span>
        <select
          value={indexOfRange(prices, value.minAmount, value.maxAmount)}
          onChange={(e) => {
            const r = prices[Number(e.target.value)]
            onChange({ ...value, minAmount: r.min, maxAmount: r.max })
          }}
        >
          {prices.map((p, i) => (
            <option key={p.label} value={i}>
              {p.label}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span>{type === 'apt' ? '전용면적' : type === 'commercial' ? '건물면적' : '거래면적'}</span>
        <select
          value={indexOfRange(areas, value.minArea, value.maxArea)}
          onChange={(e) => {
            const r = areas[Number(e.target.value)]
            onChange({ ...value, minArea: r.min, maxArea: r.max })
          }}
        >
          {areas.map((a, i) => (
            <option key={a.label} value={i}>
              {a.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
