import { useEffect, useRef, useState } from 'react'
import { fetchSearchIndex } from '../lib/api'
import type { SearchItem } from '../types'

interface Props {
  onPick: (item: SearchItem) => void
  /** 첫화면 중앙의 큰 검색창 모드 */
  hero?: boolean
}

export default function SearchBox({ onPick, hero }: Props) {
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<SearchItem[] | null>(null)
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)

  // 검색 인덱스는 전국 1파일이라 첫 입력 시점에 한 번만 받아온다 (3.3).
  useEffect(() => {
    if (!query || items) return
    fetchSearchIndex()
      .then((d) => setItems(d.items))
      .catch(() => setItems([]))
  }, [query, items])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const q = query.trim()
  const results = q && items ? items.filter((it) => it.n.includes(q) || it.a.includes(q)).slice(0, 12) : []

  return (
    <div className={hero ? 'search hero' : 'search'} ref={boxRef}>
      <input
        type="search"
        value={query}
        // 모바일에서는 자동 포커스가 키보드를 바로 띄워 첫인상을 해친다 — 포인터 환경에서만.
        autoFocus={hero && window.matchMedia('(hover: hover)').matches}
        placeholder={hero ? '단지명이나 지역으로 검색 — 예: 반포자이, 수원시' : '단지명 · 지역 검색'}
        aria-label="단지명 또는 지역 검색"
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
      />
      {open && q && (
        <ul className="search-results">
          {!items && <li className="search-empty">인덱스 불러오는 중…</li>}
          {items && !results.length && <li className="search-empty">검색 결과가 없습니다.</li>}
          {results.map((it) => (
            <li key={it.i}>
              <button
                type="button"
                onClick={() => {
                  onPick(it)
                  setOpen(false)
                  setQuery('')
                }}
              >
                <b>{it.n}</b>
                <span>{it.a}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
