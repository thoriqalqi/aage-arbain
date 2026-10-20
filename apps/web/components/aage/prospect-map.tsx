"use client"

// Peta prospek Leaflet dengan tile OpenStreetMap resmi (gratis, tanpa API key). Di-load dinamis tanpa SSR.
// Setiap hasil "Petakan" punya scanId baru → LayerGroup lama di-unmount sehingga semua pin lama terhapus dari peta.

import "leaflet/dist/leaflet.css"

import { useEffect } from "react"
import { CircleMarker, LayerGroup, MapContainer, Popup, TileLayer, useMap } from "react-leaflet"

import type { Prospect } from "@/lib/types"

export type Gudang = { nama: string; lat: number; lng: number }

// Leaflet butuh warna literal → baca dari token CSS agar tidak ada hex lepas.
const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

function FitToPins({ items, gudang, scanId }: { items: Prospect[]; gudang: Gudang; scanId: number }) {
  const map = useMap()
  useEffect(() => {
    const pts = items.filter((p) => p.lat != null && p.lng != null).map((p) => [p.lat as number, p.lng as number] as [number, number])
    if (pts.length) map.fitBounds([...pts, [gudang.lat, gudang.lng]], { padding: [36, 36], maxZoom: 14 })
    else map.setView([gudang.lat, gudang.lng], 12)
  }, [map, scanId]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

export default function ProspectMap({
  items,
  gudang,
  scanId,
  onSelect,
}: {
  items: Prospect[]
  gudang: Gudang
  scanId: number
  onSelect: (p: Prospect) => void
}) {
  const c = { stroke: token("--navy-900"), hi: token("--navy-700"), mid: token("--blue-500"), lo: token("--blue-300"), wh: token("--ok") }
  const pts = items.filter((p) => p.lat != null && p.lng != null)
  return (
    <MapContainer center={[gudang.lat, gudang.lng]} zoom={12} scrollWheelZoom className="h-full w-full">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
      />
      <FitToPins items={pts} gudang={gudang} scanId={scanId} />
      <CircleMarker center={[gudang.lat, gudang.lng]} radius={9} pathOptions={{ color: "#fff", weight: 3, fillColor: c.wh, fillOpacity: 1 }}>
        <Popup>
          <strong>{gudang.nama}</strong>
          <br />
          Titik acuan jarak (Haversine)
        </Popup>
      </CircleMarker>
      <LayerGroup key={scanId}>
        {pts.map((p) => (
          <CircleMarker
            key={p.id}
            center={[p.lat as number, p.lng as number]}
            radius={6 + p.skor / 16}
            pathOptions={{ color: c.stroke, weight: 1, fillColor: p.skor >= 70 ? c.hi : p.skor >= 45 ? c.mid : c.lo, fillOpacity: 0.9 }}
            eventHandlers={{ click: () => onSelect(p) }}
          >
            <Popup>
              <div style={{ minWidth: 200, lineHeight: 1.45 }}>
                <strong>{p.nama}</strong>
                <br />
                {p.alamat}
                <br />
                Jarak dari gudang: <strong>{p.jarak_km != null ? `${p.jarak_km.toLocaleString("id-ID")} km` : "—"}</strong>
                <br />
                Opportunity Score: <strong>{p.skor}</strong> / 100
                <br />
                <span style={{ opacity: 0.7 }}>
                  Geo {p.skor_geo?.toLocaleString("id-ID")} / 70 · Data {p.skor_data} / 30
                </span>
              </div>
            </Popup>
          </CircleMarker>
        ))}
      </LayerGroup>
    </MapContainer>
  )
}
