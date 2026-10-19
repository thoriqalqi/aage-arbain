"use client"

// Peta prospek (opsional, Leaflet + tile terang). Di-load dinamis tanpa SSR.

import "leaflet/dist/leaflet.css"

import { CircleMarker, MapContainer, Popup, TileLayer } from "react-leaflet"

import type { Prospect } from "@/lib/types"

// Leaflet butuh warna literal → baca dari token CSS agar tidak ada hex lepas.
const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()

export default function ProspectMap({ items, onSelect }: { items: Prospect[]; onSelect: (p: Prospect) => void }) {
  const c = { stroke: token("--navy-900"), hi: token("--blue-500"), mid: token("--blue-400"), lo: token("--chart-5") }
  const pts = items.filter((p) => p.lat != null && p.lng != null)
  const center: [number, number] = pts.length ? [pts[0].lat as number, pts[0].lng as number] : [-6.9932, 110.4203]
  return (
    <MapContainer center={center} zoom={12} scrollWheelZoom className="h-[560px] w-full rounded-lg">
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'
        url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
      />
      {pts.map((p) => (
        <CircleMarker
          key={p.id}
          center={[p.lat as number, p.lng as number]}
          radius={6 + p.skor / 14}
          pathOptions={{ color: c.stroke, weight: 1, fillColor: p.skor >= 75 ? c.hi : p.skor >= 55 ? c.mid : c.lo, fillOpacity: 0.85 }}
          eventHandlers={{ click: () => onSelect(p) }}
        >
          <Popup>
            <strong>{p.nama}</strong>
            <br />
            Skor {p.skor} · {p.jarak_km ?? "?"} km
          </Popup>
        </CircleMarker>
      ))}
    </MapContainer>
  )
}
