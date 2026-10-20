"use client"

import { AlertTriangle, Clock, Download, LoaderCircle, MapPinned, Phone, Radar } from "lucide-react"
import dynamic from "next/dynamic"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { ScoreBar } from "@/components/aage/charts"
import { EmptyState } from "@/components/aage/empty-state"
import { CardHeader, PageHeader, Panel, Surface } from "@/components/aage/panel"
import { ProspectDrawer, STATUS } from "@/components/aage/prospect-drawer"
import type { Gudang } from "@/components/aage/prospect-map"
import { ApiError, api, fetcher, getToken } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import type { Prospect } from "@/lib/types"
import { cn } from "@/lib/utils"

const ProspectMap = dynamic(() => import("@/components/aage/prospect-map"), {
  ssr: false,
  loading: () => <div className="shimmer h-full w-full" />,
})

const JENIS = ["Apotek", "Toko Obat", "Minimarket"] as const
const field = "h-10 rounded-[10px] border border-line bg-white px-3 text-[14px] outline-none focus:border-blue-500"
const DEFAULT_GUDANG: Gudang = { nama: "Pusat Logistik CV Arba'in — Semarang", lat: -6.9932, lng: 110.4203 }

type ScoutResponse = {
  wilayah: string
  jenis_toko: string
  sumber: "osm_live" | "cache" | "diproses"
  area_osm?: string
  jumlah: number
  baru?: number
  dilewati_tanpa_nama?: number
  durasi_ms: number
  terakhir_dipindai: string | null
  peringatan: string | null
  gudang: Gudang
  items: Prospect[]
}

export default function ProspekPage() {
  const { data: initial } = useSWR<{ items: Prospect[]; wilayah: string[]; gudang: Gudang }>("/api/prospects?wilayah=Kota%20Semarang&tipe=Apotek", fetcher)
  const [wilayah, setWilayah] = useState("Kota Semarang")
  const [jenis, setJenis] = useState<(typeof JENIS)[number]>("Apotek")
  const [result, setResult] = useState<ScoutResponse | null>(null)
  const [items, setItems] = useState<Prospect[] | null>(null)
  const [scanId, setScanId] = useState(0)
  const [loading, setLoading] = useState(false)
  const [waitingBg, setWaitingBg] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Prospect | null>(null)

  const shown = useMemo(() => items ?? initial?.items ?? [], [items, initial])
  const gudang = result?.gudang ?? initial?.gudang ?? DEFAULT_GUDANG

  async function petakan() {
    setLoading(true)
    setError(null)
    setItems([]) // bersihkan semua pin lama sebelum memuat hasil baru
    setScanId((n) => n + 1)
    try {
      const res = await api<ScoutResponse>("/api/prospek/scout", { method: "POST", json: { wilayah, jenis_toko: jenis } })
      setResult(res)
      if (res.sumber === "diproses") {
        await waitForBackground(res.wilayah, res.jenis_toko)
        return
      }
      setItems(res.items)
      setScanId((n) => n + 1)
      if (res.sumber === "cache") toast.warning("Overpass sedang penuh — menampilkan hasil pindaian terakhir")
      else toast.success(`${res.jumlah} ${jenis.toLowerCase()} dari OpenStreetMap (${res.baru ?? 0} baru)`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memindai wilayah")
      setItems(null)
    } finally {
      setLoading(false)
    }
  }

  /** Server OSM lambat: backend melanjutkan pindaian di latar; pantau tiap 5 detik (maks ±2,5 menit). */
  async function waitForBackground(w: string, t: string) {
    setWaitingBg(true)
    try {
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 5000))
        const res = await api<{ items: Prospect[]; pindaian_latar: boolean }>(
          `/api/prospects?wilayah=${encodeURIComponent(w)}&tipe=${encodeURIComponent(t)}`,
        )
        if (res.items.length || !res.pindaian_latar) {
          setItems(res.items)
          setScanId((n) => n + 1)
          setResult((r) => (r ? { ...r, sumber: "osm_live", jumlah: res.items.length, peringatan: null, terakhir_dipindai: res.items[0]?.terakhir_dipindai ?? null } : r))
          if (res.items.length) toast.success(`${res.items.length} ${t.toLowerCase()} dari OpenStreetMap`)
          else setError("Pindaian latar selesai tanpa hasil — server OSM mungkin masih penuh. Coba Petakan lagi.")
          return
        }
      }
      setError("Server OSM belum menjawab dalam 2,5 menit. Coba Petakan lagi nanti.")
    } finally {
      setWaitingBg(false)
    }
  }

  async function setStatus(p: Prospect, status: Prospect["status"]) {
    const updated = await api<Prospect>(`/api/prospects/${p.id}`, { method: "PATCH", json: { status } })
    setSelected(updated)
    setItems(shown.map((x) => (x.id === p.id ? updated : x)))
  }

  async function exportCsv() {
    const w = result?.wilayah ?? wilayah
    const t = result?.jenis_toko ?? jenis
    const res = await fetch(`/api/prospects/export.csv?wilayah=${encodeURIComponent(w)}&tipe=${encodeURIComponent(t)}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    const a = document.createElement("a")
    a.href = URL.createObjectURL(await res.blob())
    a.download = `prospek-${w.replace(/\s+/g, "-").toLowerCase()}-${t.replace(/\s+/g, "-").toLowerCase()}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const zonaEmas = shown.filter((p) => p.skor_geo === 70).length

  return (
    <div className="space-y-5">
      <PageHeader
        title="Prospek"
        description="Live Lead Scouting dari OpenStreetMap (tanpa API key) dalam batas wilayah administratif, lalu Opportunity Score 0–100 yang dihitung deterministik: kecocokan geografis 70 + kelengkapan data 30."
      />

      <Panel className="flex flex-wrap items-end gap-3 p-4">
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Wilayah administratif (nama di OSM)
          <input
            list="wilayah-list"
            value={wilayah}
            onChange={(e) => setWilayah(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !loading && petakan()}
            className={cn(field, "w-64")}
          />
          <datalist id="wilayah-list">
            {[...new Set(["Kota Semarang", "Kabupaten Semarang", "Kota Surakarta", "Kota Salatiga", "Kabupaten Kudus", "Kabupaten Demak", "Kabupaten Kendal", ...(initial?.wilayah ?? [])])].map((w) => (
              <option key={w} value={w} />
            ))}
          </datalist>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Jenis toko
          <select value={jenis} onChange={(e) => setJenis(e.target.value as (typeof JENIS)[number])} className={field}>
            {JENIS.map((j) => (
              <option key={j}>{j}</option>
            ))}
          </select>
        </label>
        <AButton onClick={petakan} disabled={loading || waitingBg || wilayah.trim().length < 2}>
          {loading || waitingBg ? <LoaderCircle className="size-4 animate-spin" /> : <MapPinned className="size-4" />} Petakan
        </AButton>
        <div className="ml-auto flex items-center gap-2">
          {result && (
            <span className="text-[12px] text-muted-foreground">
              {result.sumber === "osm_live" ? "OSM live" : result.sumber === "cache" ? "Cache pindaian terakhir" : "Diproses di latar"} · {(result.durasi_ms / 1000).toFixed(1).replace(".", ",")} dtk ·{" "}
              {formatDateTime(result.terakhir_dipindai)}
            </span>
          )}
          <AButton variant="outline" onClick={exportCsv} disabled={!shown.length}>
            <Download className="size-4" /> CSV
          </AButton>
        </div>
      </Panel>

      {(error || (result?.peringatan && !waitingBg)) && (
        <div className={cn("flex items-start gap-2 rounded-[12px] border px-4 py-3 text-[13px]", error ? "border-blocked/30 bg-blocked-bg text-blocked" : "border-review/30 bg-review-bg text-review")}>
          <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {error ?? result?.peringatan}
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel className="relative isolate z-0 h-[520px] overflow-hidden p-0">
          <ProspectMap items={shown} gudang={gudang} scanId={scanId} onSelect={setSelected} />
          {(loading || waitingBg) && (
            <div className="absolute inset-0 z-[500] flex flex-col items-center justify-center gap-3 bg-white/60 backdrop-blur-[2px]">
              <span className="btn-glass flex items-center gap-2 rounded-full px-4 py-2 text-[13px] font-medium text-navy-900">
                <Radar className="size-4 animate-spin" /> Memindai {jenis.toLowerCase()} di {wilayah}…
              </span>
              <span className="max-w-sm text-center text-[12px] text-muted-foreground">
                {waitingBg
                  ? "Server OpenStreetMap sedang lambat — pindaian dilanjutkan di latar, hasil muncul otomatis."
                  : "OpenStreetMap Overpass · batas waktu 25 detik"}
              </span>
            </div>
          )}
        </Panel>
        <Panel className="p-5">
          <CardHeader icon={<Radar />} title="Ringkasan pindaian" />
          <dl className="mt-4 grid grid-cols-2 gap-3 text-[13px]">
            <div className="rounded-xl bg-soft p-3">
              <dt className="text-muted-foreground">Toko ditemukan</dt>
              <dd className="tabular text-[24px] font-semibold">{shown.length}</dd>
            </div>
            <div className="rounded-xl bg-soft p-3">
              <dt className="text-muted-foreground">Zona emas 2–8 km</dt>
              <dd className="tabular text-[24px] font-semibold">{zonaEmas}</dd>
            </div>
            <div className="rounded-xl bg-soft p-3">
              <dt className="text-muted-foreground">Ada telepon</dt>
              <dd className="tabular text-[24px] font-semibold">{shown.filter((p) => p.telepon).length}</dd>
            </div>
            <div className="rounded-xl bg-soft p-3">
              <dt className="text-muted-foreground">Ada jam buka</dt>
              <dd className="tabular text-[24px] font-semibold">{shown.filter((p) => p.jam_buka).length}</dd>
            </div>
          </dl>
          {result?.dilewati_tanpa_nama ? (
            <p className="mt-3 text-[12px] text-subtle-foreground">{result.dilewati_tanpa_nama} titik tanpa nama di OSM tidak dimasukkan.</p>
          ) : null}
          <div className="mt-4 space-y-1.5 text-[12px] text-muted-foreground">
            <div className="flex items-center gap-2"><span className="size-3 rounded-full bg-navy-700" /> Skor ≥ 70</div>
            <div className="flex items-center gap-2"><span className="size-3 rounded-full bg-blue-500" /> Skor 45–69</div>
            <div className="flex items-center gap-2"><span className="size-3 rounded-full bg-blue-300" /> Skor &lt; 45</div>
            <div className="flex items-center gap-2"><span className="size-3 rounded-full border-2 border-white bg-ok shadow" /> {gudang.nama}</div>
          </div>
        </Panel>
      </div>

      <Surface className="overflow-x-auto">
        {shown.length === 0 ? (
          <EmptyState
            icon={<MapPinned />}
            title={loading ? "Memindai…" : "Belum ada prospek"}
            description="Pilih wilayah dan jenis toko, lalu klik Petakan untuk memindai toko nyata dari OpenStreetMap."
          />
        ) : (
          <table className="w-full text-[13px]">
            <thead className="bg-soft text-left text-[11.5px] tracking-[0.04em] text-muted-foreground uppercase">
              <tr>
                <th className="sticky left-0 bg-soft px-4 py-2.5 font-medium">Skor</th>
                <th className="px-3 py-2.5 font-medium">Nama & alamat</th>
                <th className="px-3 py-2.5 font-medium">Jarak</th>
                <th className="px-3 py-2.5 font-medium">Telepon</th>
                <th className="px-3 py-2.5 font-medium">Jam buka</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr key={p.id} onClick={() => setSelected(p)} className="cursor-pointer border-t border-line bg-white hover:bg-blue-50">
                  <td className="sticky left-0 bg-inherit px-4 py-2.5">
                    <ScoreBar score={p.skor} reasons={p.alasan_skor} />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="font-medium">{p.nama}</div>
                    <div className={cn("line-clamp-1 text-[12px]", p.alamat_jalan_ada ? "text-muted-foreground" : "text-subtle-foreground italic")}>{p.alamat}</div>
                  </td>
                  <td className="tabular px-3 py-2.5 whitespace-nowrap">{p.jarak_km != null ? `${p.jarak_km.toLocaleString("id-ID")} km` : "—"}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap text-muted-foreground">
                    {p.telepon ? (
                      <span className="inline-flex items-center gap-1"><Phone className="size-3.5" /> {p.telepon}</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="max-w-[12rem] px-3 py-2.5 text-muted-foreground">
                    {p.jam_buka ? (
                      <span className="inline-flex items-center gap-1"><Clock className="size-3.5 shrink-0" /> <span className="truncate">{p.jam_buka}</span></span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={cn("inline-flex h-6 items-center rounded-full px-2 text-[12px] font-medium", STATUS[p.status].cls)}>{STATUS[p.status].label}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Surface>
      <p className="text-[11.5px] text-subtle-foreground">
        Data © OpenStreetMap contributors (ODbL). AAGE tidak mengirim pesan massal — staf yang menghubungi prospek.
      </p>
      <ProspectDrawer
        p={selected}
        onClose={() => setSelected(null)}
        onStatus={setStatus}
        onUpdated={(u) => {
          setSelected(u)
          setItems(shown.map((x) => (x.id === u.id ? u : x)))
        }}
      />
    </div>
  )
}
