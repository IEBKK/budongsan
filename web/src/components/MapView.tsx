import { useEffect, useRef } from 'react'
import L from 'leaflet'
import Supercluster from 'supercluster'
import 'leaflet/dist/leaflet.css'
import { markerLabel } from '../lib/format'
import { REGION_ZOOM_MAX, type ViewState } from '../hooks/useVisibleData'
import { isAuction, type PropertyType, type RegionSummary, type VisibleItem } from '../types'

interface Props {
  center: [number, number]
  zoom: number
  type: PropertyType
  regions: RegionSummary[]
  items: VisibleItem[]
  selectedId: string | null
  hoveredId: string | null
  flyTo: { lat: number; lng: number; zoom: number; key: number } | null
  onViewChange: (view: ViewState) => void
  onSelect: (item: VisibleItem) => void
  onHover: (id: string | null) => void
}

type ClusterProps = { item: VisibleItem }

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch]!)
}

/** 마커에 찍히는 값: 실거래는 중위 거래가, 공매는 최저입찰가 */
function markerAmount(item: VisibleItem): number {
  return isAuction(item) ? item.minBid : item.filteredMedian
}

function tooltipText(item: VisibleItem): string {
  return isAuction(item)
    ? `${item.name} · ${item.bidRate !== null ? `감정가의 ${Math.round(item.bidRate)}%` : '감정가 미상'}`
    : `${item.name} · ${item.filteredCount}건`
}

export default function MapView(props: Props) {
  const { type, regions, items, selectedId, hoveredId, flyTo, onViewChange, onSelect, onHover } = props
  const hostRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)
  // 콜백을 ref 로 들고 있어야 map 을 재생성하지 않고도 최신 핸들러를 쓸 수 있다.
  const cb = useRef({ onViewChange, onSelect, onHover })
  cb.current = { onViewChange, onSelect, onHover }

  useEffect(() => {
    if (!hostRef.current || mapRef.current) return
    const map = L.map(hostRef.current, {
      center: props.center,
      zoom: props.zoom,
      zoomControl: true,
      preferCanvas: true,
    })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map)
    layerRef.current = L.layerGroup().addTo(map)

    const emit = () => {
      const b = map.getBounds()
      cb.current.onViewChange({
        zoom: map.getZoom(),
        north: b.getNorth(),
        south: b.getSouth(),
        east: b.getEast(),
        west: b.getWest(),
      })
    }
    map.on('moveend', emit)
    map.on('zoomend', emit)
    emit()
    mapRef.current = map
    // 레이아웃이 잡힌 뒤 크기를 다시 계산 (모바일 토글 대비)
    setTimeout(() => map.invalidateSize(), 0)
    return () => {
      map.remove()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (flyTo && mapRef.current) mapRef.current.setView([flyTo.lat, flyTo.lng], flyTo.zoom)
  }, [flyTo])

  // 마커 다시 그리기: 줌 구간에 따라 시군구 집계 / 개별 항목 클러스터를 전환한다.
  useEffect(() => {
    const map = mapRef.current
    const layer = layerRef.current
    if (!map || !layer) return
    layer.clearLayers()
    const zoom = map.getZoom()

    // 공매는 전국 건수가 적어 줌 단계와 무관하게 개별 물건을 그린다.
    if (type !== 'auction' && zoom <= REGION_ZOOM_MAX) {
      for (const r of regions) {
        const marker = L.marker([r.lat, r.lng], {
          icon: L.divIcon({
            className: 'marker-wrap',
            html: `<div class="marker region"><b>${escapeHtml(r.name)}</b><span>${
              r.pricePerPyeong ? `${Math.round(r.pricePerPyeong).toLocaleString()}만/평` : '거래 없음'
            }</span></div>`,
            iconSize: [0, 0],
          }),
        })
        marker.on('click', () => map.setView([r.lat, r.lng], REGION_ZOOM_MAX + 2))
        marker.addTo(layer)
      }
      return
    }

    const index = new Supercluster<ClusterProps>({ radius: 62, maxZoom: 17, minPoints: 3 })
    index.load(
      items.map((item) => ({
        type: 'Feature' as const,
        properties: { item },
        geometry: { type: 'Point' as const, coordinates: [item.lng, item.lat] },
      })),
    )
    const b = map.getBounds()
    const clusters = index.getClusters(
      [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()],
      Math.round(zoom),
    )

    for (const feature of clusters) {
      const [lng, lat] = feature.geometry.coordinates
      const cp = feature.properties as { cluster?: boolean; point_count?: number } & ClusterProps

      if (cp.cluster) {
        const count = cp.point_count ?? 0
        const size = count > 200 ? 54 : count > 50 ? 46 : 38
        L.marker([lat, lng], {
          icon: L.divIcon({
            className: 'marker-wrap',
            html: `<div class="cluster ${type}" style="width:${size}px;height:${size}px">${count}</div>`,
            iconSize: [0, 0],
          }),
        })
          .on('click', () => {
            const target = Math.min(
              index.getClusterExpansionZoom((feature as unknown as { id: number }).id),
              18,
            )
            map.setView([lat, lng], target)
          })
          .addTo(layer)
        continue
      }

      const item = cp.item
      const state = item.id === selectedId ? ' selected' : item.id === hoveredId ? ' hovered' : ''
      const badge = isAuction(item) && item.isNew ? '<i class="new-dot"></i>' : ''
      const marker = L.marker([lat, lng], {
        icon: L.divIcon({
          className: 'marker-wrap',
          html: `<div class="marker price ${type}${state}${
            item.geo === 'approx' ? ' approx' : ''
          }">${badge}${markerLabel(markerAmount(item))}</div>`,
          iconSize: [0, 0],
        }),
        zIndexOffset: item.id === selectedId ? 1000 : 0,
      })
      marker.on('click', () => cb.current.onSelect(item))
      marker.on('mouseover', () => cb.current.onHover(item.id))
      marker.on('mouseout', () => cb.current.onHover(null))
      marker.bindTooltip(escapeHtml(tooltipText(item)), { direction: 'top', offset: [0, -14] })
      marker.addTo(layer)
    }
  }, [type, regions, items, selectedId, hoveredId])

  return <div className="map" ref={hostRef} role="application" aria-label="물건 지도" />
}
