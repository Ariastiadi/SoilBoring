import { useEffect, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { t } from './i18n'

type Row = Record<string, any>

const COLORS = ['#0369a1', '#b45309', '#047857', '#7c3aed', '#be123c', '#0f766e', '#4d7c0f', '#a21caf']

/** Borehole locations on OpenStreetMap; click a point to open that borehole. */
export default function BoreholeMap({ reports, onOpen }: { reports: Row[], onOpen: (id: string) => void }) {
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)

  useEffect(() => {
    if (!box.current || map.current) return
    map.current = L.map(box.current, { scrollWheelZoom: false }).setView([-2.5, 118], 5)
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      // Tiles load with CORS (needed by the page's cross-origin isolation) and send the site origin.
      crossOrigin: 'anonymous',
      referrerPolicy: 'strict-origin-when-cross-origin',
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    } as L.TileLayerOptions).addTo(map.current)
    layer.current = L.layerGroup().addTo(map.current)
    return () => {
      map.current?.remove()
      map.current = null
    }
  }, [])

  useEffect(() => {
    if (!map.current || !layer.current) return
    layer.current.clearLayers()
    const projects = [...new Set(reports.map(r => r.ProjectName))]
    const points: L.LatLngExpression[] = []
    reports.forEach(r => {
      const lat = parseFloat(r.Latitude), lon = parseFloat(r.Longitude)
      if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return
      points.push([lat, lon])
      const popup = document.createElement('div')
      const title = document.createElement('strong')
      title.textContent = r.BoreholeID
      const info = document.createElement('div')
      info.textContent = `${r.ProjectName || ''} · ${r.SiteName || ''} · ${r.FinalDepth_m || '–'} m · ${r.USCS_Class || ''}`
      const open = document.createElement('button')
      open.textContent = t('Open')
      open.style.marginTop = '.4rem'
      open.onclick = () => onOpen(r.BoreholeID)
      popup.append(title, info, open)
      L.circleMarker([lat, lon], {
        radius: 7, weight: 2, color: '#fff', fillOpacity: 0.9,
        fillColor: COLORS[projects.indexOf(r.ProjectName) % COLORS.length],
      }).bindPopup(popup).bindTooltip(String(r.BoreholeID)).addTo(layer.current!)
    })
    if (points.length === 1) map.current.setView(points[0], 15)
    else if (points.length > 1) map.current.fitBounds(L.latLngBounds(points), { padding: [30, 30], maxZoom: 16 })
  }, [reports, onOpen])

  const withCoords = reports.filter(r => Number.isFinite(parseFloat(r.Latitude)) && Number.isFinite(parseFloat(r.Longitude))).length
  return (
    <div>
      <div ref={box} className="map-box" />
      <p style={{ color: 'var(--muted)', fontSize: '.85rem', margin: '.5rem 0 0' }}>
        {t('{n} of {total} boreholes have coordinates. Colours show projects.', { n: withCoords, total: reports.length })}
      </p>
    </div>
  )
}
