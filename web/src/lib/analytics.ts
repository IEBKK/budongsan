/** GA4 (3.5). VITE_GA_ID 가 있을 때만 스크립트를 주입한다. */
const GA_ID = import.meta.env.VITE_GA_ID as string | undefined

declare global {
  interface Window {
    dataLayer?: unknown[]
    gtag?: (...args: unknown[]) => void
  }
}

export function initAnalytics(): void {
  if (!GA_ID || document.getElementById('ga4')) return
  const s = document.createElement('script')
  s.id = 'ga4'
  s.async = true
  s.src = `https://www.googletagmanager.com/gtag/js?id=${GA_ID}`
  document.head.appendChild(s)
  window.dataLayer = window.dataLayer || []
  window.gtag = function gtag(...args: unknown[]) {
    window.dataLayer!.push(args)
  }
  window.gtag('js', new Date())
  window.gtag('config', GA_ID)
}

/** 유형 탭별 조회수 등 커스텀 이벤트 (3.5 측정 항목) */
export function track(name: string, params: Record<string, unknown> = {}): void {
  window.gtag?.('event', name, params)
}
