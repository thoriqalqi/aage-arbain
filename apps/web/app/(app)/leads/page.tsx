"use client"

import { AlertTriangle, CalendarClock, ChevronRight, Clock, Download, LoaderCircle, MapPinned, MessageCircle, Phone, Plus, Radar, Search } from "lucide-react"
import dynamic from "next/dynamic"
import { useEffect, useMemo, useState } from "react"
import { toast } from "sonner"
import useSWR, { mutate as simpanCache } from "swr"

import { AButton } from "@/components/aage/button"
import { ScoreBar } from "@/components/aage/charts"
import { EmptyState, SkeletonRows } from "@/components/aage/empty-state"
import { LeadBaru } from "@/components/aage/lead-baru"
import { VERIFIKASI } from "@/components/aage/lead-detail"
import { GalatMuat, LeadsNav } from "@/components/aage/leads-nav"
import { CardHeader, PageHeader, Panel, Surface } from "@/components/aage/panel"
import { CONSENT, ProspectDrawer, STATUS } from "@/components/aage/prospect-drawer"
import type { Gudang } from "@/components/aage/prospect-map"
import { ApiError, api, fetcher, unduh } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import { useRole } from "@/lib/rbac"
import type { DaftarLead, Prospect } from "@/lib/types"
import { cn } from "@/lib/utils"

const ProspectMap = dynamic(() => import("@/components/aage/prospect-map"), {
  ssr: false,
  loading: () => <div className="shimmer h-full w-full" />,
})

const JENIS = ["Apotek", "Toko Obat", "Minimarket"] as const
const field = "h-10 rounded-[10px] border border-line bg-white px-3 text-[14px] outline-none focus:border-brand-500"
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

const FILTER_KOSONG = { q: "", tipe: "", wilayah: "", status: "", verifikasi: "", consent_status: "", sumber: "", skor_min: "" }
type Filter = typeof FILTER_KOSONG

function urlDaftar(f: Filter): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(f)) if (v) q.set(k, v)
  return q.size ? `/api/prospects?${q}` : "/api/prospects"
}

export default function ProspekPage() {
  const { actual } = useRole()
  const [filter, setFilter] = useState<Filter>(FILTER_KOSONG)
  const [cari, setCari] = useState("")
  const urlAktif = urlDaftar(filter)
  const { data, error: galatMuat, isLoading, mutate } = useSWR<DaftarLead>(urlAktif, fetcher, { keepPreviousData: true })
  const [wilayah, setWilayah] = useState("Kota Semarang")
  const [jenis, setJenis] = useState<(typeof JENIS)[number]>("Apotek")
  const [result, setResult] = useState<ScoutResponse | null>(null)
  const [memindai, setMemindai] = useState(false)
  const [scanId, setScanId] = useState(0)
  const [loading, setLoading] = useState(false)
  const [waitingBg, setWaitingBg] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Prospect | null>(null)
  const [tambah, setTambah] = useState(false)

  const shown = useMemo(() => (memindai ? [] : (data?.items ?? [])), [memindai, data])
  const gudang = result?.gudang ?? data?.gudang ?? DEFAULT_GUDANG
  const segmen = data?.segmen ?? [...JENIS]
  const adaFilter = Object.values(filter).some(Boolean)
  const idPeta = shown.map((p) => p.id).join(",")

  useEffect(() => {
    const t = setTimeout(() => setFilter((f) => (f.q === cari.trim() ? f : { ...f, q: cari.trim() })), 300)
    return () => clearTimeout(t)
  }, [cari])

  // Peta menyesuaikan diri setiap isi daftar berganti, bukan saat status satu lead berubah.
  useEffect(() => setScanId((n) => n + 1), [idPeta])

  function setF<K extends keyof Filter>(k: K, v: Filter[K]) {
    setFilter((f) => ({ ...f, [k]: v }))
  }

  /** Setelah pindai, daftar menampilkan wilayah dan jenis yang baru dipindai. */
  async function tampilkanHasil(w: string, t: string): Promise<number> {
    const f = { ...FILTER_KOSONG, wilayah: w, tipe: t }
    const url = urlDaftar(f)
    const hasil = await api<DaftarLead>(url)
    await simpanCache(url, hasil, false)
    setCari("")
    setFilter(f)
    setMemindai(false)
    return hasil.items.length
  }

  async function petakan() {
    setLoading(true)
    setError(null)
    setMemindai(true) // bersihkan semua pin lama sebelum memuat hasil baru
    try {
      const res = await api<ScoutResponse>("/api/prospek/scout", { method: "POST", json: { wilayah, jenis_toko: jenis } })
      setResult(res)
      if (res.sumber === "diproses") {
        await waitForBackground(res.wilayah, res.jenis_toko)
        return
      }
      await tampilkanHasil(res.wilayah, res.jenis_toko)
      if (res.sumber === "cache") toast.warning("Overpass sedang penuh, menampilkan hasil pindaian terakhir")
      else toast.success(`${res.jumlah} ${jenis.toLowerCase()} dari OpenStreetMap (${res.baru ?? 0} baru)`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Gagal memindai wilayah")
    } finally {
      setMemindai(false)
      setLoading(false)
    }
  }

  /** Server OSM lambat: backend melanjutkan pindaian di latar; pantau tiap 5 detik (maks ±2,5 menit). */
  async function waitForBackground(w: string, t: string) {
    setWaitingBg(true)
    try {
      const url = urlDaftar({ ...FILTER_KOSONG, wilayah: w, tipe: t })
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 5000))
        const res = await api<DaftarLead>(url)
        if (res.items.length || !res.pindaian_latar) {
          const n = await tampilkanHasil(w, t)
          setResult((r) => (r ? { ...r, sumber: "osm_live", jumlah: n, peringatan: null, terakhir_dipindai: res.items[0]?.terakhir_dipindai ?? null } : r))
          if (n) toast.success(`${n} ${t.toLowerCase()} dari OpenStreetMap`)
          else setError("Pindaian latar selesai tanpa hasil. Server OSM mungkin masih penuh, coba Petakan lagi.")
          return
        }
      }
      setError("Server OSM belum menjawab dalam 2,5 menit. Coba Petakan lagi nanti.")
    } finally {
      setWaitingBg(false)
    }
  }

  function perbarui(u: Prospect) {
    setSelected(u)
    void mutate()
  }

  async function setStatus(p: Prospect, status: Prospect["status"]) {
    try {
      perbarui(await api<Prospect>(`/api/prospects/${p.id}`, { method: "PATCH", json: { status } }))
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Status gagal disimpan")
    }
  }

  async function bukaLead(id: number) {
    try {
      setSelected(await api<Prospect>(`/api/prospects/${id}`))
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Lead tidak bisa dibuka")
    }
  }

  async function exportCsv() {
    const q = new URLSearchParams()
    if (filter.wilayah) q.set("wilayah", filter.wilayah)
    if (filter.tipe) q.set("tipe", filter.tipe)
    const nama = [filter.wilayah, filter.tipe].filter(Boolean).join("-").replace(/\s+/g, "-").toLowerCase() || "semua"
    try {
      await unduh(`/api/prospects/export.csv${q.size ? `?${q}` : ""}`, `prospek-${nama}.csv`)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Ekspor gagal")
    }
  }

  // Dibaca dari alasan skor, bukan angka poin, karena bobot lokasi bisa diatur admin.
  const zonaEmas = shown.filter((p) => p.alasan_skor.some((r) => r.faktor === "Geographic Fit" && r.keterangan.includes("(zona emas"))).length
  const funnel = useMemo(() => {
    const urutan: Record<string, number> = { baru: 0, dihubungi: 1, merespons: 2, pelanggan: 3 }
    const at = (n: number) => shown.filter((p) => (urutan[p.status] ?? -1) >= n).length
    return [
      { label: "Dipindai", n: shown.length },
      { label: "Dihubungi", n: at(1) },
      { label: "Merespons", n: at(2) },
      { label: "Pelanggan", n: at(3) },
    ]
  }, [shown])
  const jatuhTempo = shown.filter(
    (p) => p.tindak_lanjut_pada && new Date(p.tindak_lanjut_pada) <= new Date() && p.status !== "pelanggan" && p.status !== "menolak",
  )

  // Tautan dari Inbox dan antrean tinjauan: /leads?prospek=ID membuka drawer lead tersebut.
  useEffect(() => {
    const id = Number(new URLSearchParams(window.location.search).get("prospek"))
    if (id) void bukaLead(id)
  }, [])

  return (
    <div className="space-y-5">
      <PageHeader
        title="Leads"
        description="Lead dari OpenStreetMap, input manual, dan impor, dinilai dengan Opportunity Score sementara 0–100. Hanya kontak inbound/opt-in yang dihubungi."
        actions={
          <AButton onClick={() => setTambah(true)}>
            <Plus className="size-4" /> Tambah lead
          </AButton>
        }
      />
      <LeadsNav />

      {shown.length > 0 && (
        <Panel className="flex flex-wrap items-stretch gap-2 p-3">
          {funnel.map((f, i) => (
            <div key={f.label} className="flex min-w-[8rem] flex-1 items-center gap-2">
              <div className="flex-1 rounded-xl bg-soft px-3 py-2">
                <div className="text-[12px] text-muted-foreground">{f.label}</div>
                <div className="flex items-baseline gap-1.5">
                  <span className="tabular text-[22px] font-semibold">{f.n}</span>
                  {i > 0 && funnel[i - 1].n > 0 && (
                    <span className="text-[12px] text-subtle-foreground">{Math.round((f.n / funnel[i - 1].n) * 100)}%</span>
                  )}
                </div>
              </div>
              {i < funnel.length - 1 && <ChevronRight className="size-4 shrink-0 text-subtle-foreground" aria-hidden />}
            </div>
          ))}
          <button
            onClick={() => jatuhTempo[0] && setSelected(jatuhTempo[0])}
            disabled={!jatuhTempo.length}
            className={cn(
              "flex min-w-[9rem] flex-col justify-center rounded-xl px-3 py-2 text-left",
              jatuhTempo.length ? "bg-escalate-bg text-escalate" : "bg-soft text-muted-foreground",
            )}
          >
            <span className="flex items-center gap-1 text-[12px]"><CalendarClock className="size-3.5" /> Tindak lanjut jatuh tempo</span>
            <span className="tabular text-[22px] font-semibold">{jatuhTempo.length}</span>
          </button>
        </Panel>
      )}

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
            {[...new Set(["Kota Semarang", "Kabupaten Semarang", "Kota Surakarta", "Kota Salatiga", "Kabupaten Kudus", "Kabupaten Demak", "Kabupaten Kendal", ...(data?.wilayah ?? [])])].map((w) => (
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
          {actual === "admin" && (
            <AButton variant="outline" onClick={exportCsv} disabled={!shown.length}>
              <Download className="size-4" /> CSV
            </AButton>
          )}
        </div>
      </Panel>

      {(error || (result?.peringatan && !waitingBg)) && (
        <div className={cn("flex items-start gap-2 rounded-[12px] border px-4 py-3 text-[13px]", error ? "border-blocked/30 bg-blocked-bg text-blocked" : "border-review/30 bg-review-bg text-review")}>
          <AlertTriangle className="mt-0.5 size-4 shrink-0" /> {error ?? result?.peringatan}
        </div>
      )}

      <Panel className="flex flex-wrap items-end gap-3 p-4">
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Cari nama atau alamat
          <span className="relative">
            <Search className="absolute top-3 left-3 size-4 text-subtle-foreground" aria-hidden />
            <input value={cari} onChange={(e) => setCari(e.target.value)} className={cn(field, "w-56 pl-9")} />
          </span>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Segmen
          <select value={filter.tipe} onChange={(e) => setF("tipe", e.target.value)} className={field}>
            <option value="">Semua</option>
            {segmen.map((j) => (
              <option key={j}>{j}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Wilayah
          <select value={filter.wilayah} onChange={(e) => setF("wilayah", e.target.value)} className={cn(field, "max-w-48")}>
            <option value="">Semua</option>
            {[...new Set([...(filter.wilayah ? [filter.wilayah] : []), ...(data?.wilayah ?? [])])].map((w) => (
              <option key={w}>{w}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Skor minimal
          <select value={filter.skor_min} onChange={(e) => setF("skor_min", e.target.value)} className={field}>
            <option value="">Semua</option>
            <option value="45">45 ke atas</option>
            <option value="70">70 ke atas</option>
          </select>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Status
          <select value={filter.status} onChange={(e) => setF("status", e.target.value)} className={field}>
            <option value="">Semua</option>
            {Object.entries(STATUS).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Verifikasi
          <select value={filter.verifikasi} onChange={(e) => setF("verifikasi", e.target.value)} className={field}>
            <option value="">Semua</option>
            {Object.entries(VERIFIKASI).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Consent
          <select value={filter.consent_status} onChange={(e) => setF("consent_status", e.target.value)} className={field}>
            <option value="">Semua</option>
            {Object.entries(CONSENT).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Sumber
          <select value={filter.sumber} onChange={(e) => setF("sumber", e.target.value)} className={cn(field, "max-w-48")}>
            <option value="">Semua</option>
            {Object.entries(data?.sumber_opsi ?? {}).filter(([k]) => k !== "sintetis").map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
        {adaFilter && (
          <AButton
            variant="ghost"
            onClick={() => {
              setCari("")
              setFilter(FILTER_KOSONG)
            }}
          >
            Hapus filter
          </AButton>
        )}
      </Panel>

      {galatMuat && <GalatMuat error={galatMuat} onUlang={() => mutate()} />}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel className="relative isolate z-0 h-[520px] overflow-hidden p-0">
          <ProspectMap items={shown} gudang={gudang} scanId={scanId} onSelect={setSelected} />
          {(loading || waitingBg) && (
            <div className="absolute inset-0 z-[500] flex flex-col items-center justify-center gap-3 bg-white/60 backdrop-blur-[2px]">
              <span className="btn-glass flex items-center gap-2 rounded-full px-4 py-2 text-[13px] font-medium text-forest-900">
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
            <div className="flex items-center gap-2"><span className="size-3 rounded-full bg-forest-700" /> Skor ≥ 70</div>
            <div className="flex items-center gap-2"><span className="size-3 rounded-full bg-brand-500" /> Skor 45–69</div>
            <div className="flex items-center gap-2"><span className="size-3 rounded-full bg-brand-300" /> Skor &lt; 45</div>
            <div className="flex items-center gap-2"><span className="size-3 rounded-full border-2 border-white bg-ok shadow" /> {gudang.nama}</div>
          </div>
        </Panel>
      </div>

      <Surface className="overflow-x-auto">
        {isLoading && !data ? (
          <SkeletonRows rows={6} className="p-4" />
        ) : shown.length === 0 ? (
          adaFilter && !loading ? (
            <EmptyState
              icon={<Search />}
              title="Tidak ada lead yang cocok"
              description="Longgarkan filter, atau hapus filter untuk melihat semua lead."
            />
          ) : (
            <EmptyState
              icon={<MapPinned />}
              title={loading ? "Memindai…" : "Belum ada lead"}
              description="Klik Petakan untuk memindai toko dari OpenStreetMap, tambah lead manual, atau impor daftar dari sumber yang sah."
            />
          )
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
                <th className="px-3 py-2.5 font-medium">Consent & verifikasi</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr key={p.id} onClick={() => setSelected(p)} className="cursor-pointer border-t border-line bg-white hover:bg-brand-50">
                  <td className="sticky left-0 bg-inherit px-4 py-2.5">
                    <ScoreBar score={p.skor} reasons={p.alasan_skor} />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1.5 font-medium">
                      {p.nama}
                      {p.jaringan && <span className="rounded-full bg-review-bg px-1.5 text-[11px] font-medium text-review">Jaringan</span>}
                      {p.conversation_id && <MessageCircle className="size-3.5 text-ok" aria-label="Sudah chat WhatsApp" />}
                    </div>
                    <div className={cn("line-clamp-1 text-[12px]", p.alamat_jalan_ada ? "text-muted-foreground" : "text-subtle-foreground italic")}>{p.alamat || "Alamat kosong"}</div>
                    <div className="text-[11.5px] text-subtle-foreground">{p.tipe} · {p.sumber_label}</div>
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
                    {p.tindak_lanjut_pada && p.status !== "pelanggan" && p.status !== "menolak" && (
                      <div className={cn("mt-0.5 text-[11.5px]", new Date(p.tindak_lanjut_pada) <= new Date() ? "font-semibold text-escalate" : "text-subtle-foreground")}>
                        Follow-up {formatDateTime(p.tindak_lanjut_pada)}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    <span className={cn("inline-flex h-6 items-center rounded-full px-2 text-[12px] font-medium", CONSENT[p.consent_status].cls)}>{CONSENT[p.consent_status].label}</span>
                    <div className="mt-1">
                      <span className={cn("inline-flex h-6 items-center rounded-full px-2 text-[12px] font-medium", VERIFIKASI[p.status_verifikasi].cls)}>{VERIFIKASI[p.status_verifikasi].label}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Surface>
      <p className="text-[11.5px] text-subtle-foreground">
        {data && data.total > data.items.length && `Menampilkan ${data.items.length} dari ${data.total} lead. `}
        Skor masih sementara dan bukan izin menghubungi. Data OSM © OpenStreetMap contributors (ODbL). AAGE tidak mengirim pesan massal, staf yang menghubungi lead.
      </p>
      <ProspectDrawer p={selected} segmen={segmen} onClose={() => setSelected(null)} onStatus={setStatus} onUpdated={perbarui} />
      <LeadBaru
        open={tambah}
        segmen={segmen}
        onClose={() => setTambah(false)}
        onCreated={(p) => {
          setTambah(false)
          perbarui(p)
        }}
        onBukaLead={(id) => {
          setTambah(false)
          void bukaLead(id)
        }}
      />
    </div>
  )
}
