import type { AuctionFile, Meta, RegionSummary, SearchItem, TradeFile, TradeType } from '../types'

const BASE = `${import.meta.env.BASE_URL}data/`.replace(/\/{2,}/g, '/')

const cache = new Map<string, Promise<unknown>>()

function load<T>(path: string): Promise<T> {
  let hit = cache.get(path)
  if (!hit) {
    hit = fetch(BASE + path).then((res) => {
      if (!res.ok) throw new Error(`${path} 로딩 실패 (${res.status})`)
      return res.json()
    })
    // 실패는 캐시에 남기지 않는다 — 다음 pan 에서 재시도할 수 있어야 한다.
    hit.catch(() => cache.delete(path))
    cache.set(path, hit)
  }
  return hit as Promise<T>
}

export const fetchMeta = () => load<Meta>('meta.json')
export const fetchSearchIndex = () => load<{ items: SearchItem[] }>('search-index.json')
export const fetchAuction = () => load<AuctionFile>('auction/onbid.json')

/** 유형별 전국 시군구 요약 (줌아웃 시 집계 마커용) */
export const fetchNationSummary = (kind: TradeType) =>
  load<{ regions: RegionSummary[] }>(`summary/${kind}.json`)

const loaded = new Map<string, TradeFile>()

function key(kind: TradeType, code: string) {
  return `${kind}/${code}`
}

export async function ensureRegion(kind: TradeType, code: string): Promise<TradeFile> {
  const file = await load<TradeFile>(`${kind}/${code}.json`)
  loaded.set(key(kind, code), file)
  return file
}

/** 이미 받아둔 지역 파일만 동기적으로 꺼낸다 */
export function peekRegion(kind: TradeType, code: string): TradeFile | undefined {
  return loaded.get(key(kind, code))
}
