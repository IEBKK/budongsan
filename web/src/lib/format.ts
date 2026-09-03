/** 만원 단위 금액을 '12억 3,400' 형태로 */
export function formatAmount(manwon: number): string {
  if (!manwon) return '-'
  const eok = Math.floor(manwon / 10000)
  const rest = manwon % 10000
  if (eok === 0) return `${manwon.toLocaleString()}만`
  if (rest === 0) return `${eok}억`
  return `${eok}억 ${rest.toLocaleString()}`
}

export function formatPpp(manwon: number): string {
  return manwon > 0 ? `${Math.round(manwon).toLocaleString()}만/평` : '-'
}

export function formatYm(ym: string): string {
  return `${ym.slice(2, 4)}.${ym.slice(4, 6)}`
}

export function formatDate(ym: string, day: number): string {
  return `${ym.slice(0, 4)}.${ym.slice(4, 6)}.${String(day).padStart(2, '0')}`
}

export function pyeong(areaM2: number): number {
  return Math.round((areaM2 / 3.3058) * 10) / 10
}

/** 마커에 들어갈 짧은 라벨 (MAP-03) */
export function markerLabel(manwon: number): string {
  if (manwon >= 10000) {
    const eok = manwon / 10000
    return `${eok >= 10 ? Math.round(eok) : eok.toFixed(1).replace(/\.0$/, '')}억`
  }
  return `${Math.round(manwon / 100) / 10}천`
}

export function signed(pct: number | null): string {
  if (pct === null || Number.isNaN(pct)) return '-'
  return `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`
}

/** '부동산 / 주거용건물 / 아파트' -> '아파트' */
export function shortCategory(category: string): string {
  const parts = category.split('/').map((s) => s.trim()).filter(Boolean)
  return parts[parts.length - 1] || '기타'
}

export function formatBidRate(rate: number | null): string {
  return rate === null ? '-' : `감정가의 ${rate.toFixed(0)}%`
}

/** 마감까지 남은 일수를 사람이 읽는 문구로 */
export function formatDaysToClose(days: number | null): string {
  if (days === null) return '일정 미정'
  if (days < 0) return '마감'
  if (days === 0) return '오늘 마감'
  if (days === 1) return '내일 마감'
  return `${days}일 남음`
}

export function formatIsoDate(iso: string): string {
  if (!iso) return '-'
  const [date, time] = iso.split('T')
  return time ? `${date.replace(/-/g, '.')} ${time}` : date.replace(/-/g, '.')
}
