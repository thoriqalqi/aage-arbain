"use client"

import { Copy, Download, Globe, LoaderCircle, Map, MapPinned, Phone, Star, Table2 } from "lucide-react"
import dynamic from "next/dynamic"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { ScoreBar } from "@/components/aage/charts"
import { EmptyState, SkeletonRows } from "@/components/aage/empty-state"
import { GlassCard, PageHeader, Surface } from "@/components/aage/glass-card"
import { Pill, VerdictBadge } from "@/components/aage/status"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { api, fetcher, getToken } from "@/lib/api"
import type { Prospect } from "@/lib/types"
import { cn } from "@/lib/utils"

const ProspectMap = dynamic(() => import("@/components/aage/prospect-map"), {
  ssr: false,
  loading: () => <div className="shimmer h-[560px] rounded-lg" />,
})

const STATUS: Record<Prospect["status"], { label: string; cls: string }> = {
  baru: { label: "Baru", cls: "bg-cream-100 text-muted-foreground" },
  dihubungi: { label: "Dihubungi", cls: "bg-info-bg text-info" },
  merespons: { label: "Merespons", cls: "bg-ok-bg text-ok" },
  menolak: { label: "Menolak", cls: "bg-blocked-bg text-blocked" },
}
const SOURCE: Record<string, string> = { google_places: "Google Places", osm: "OpenStreetMap", sintetis: "Data sintetis" }
const field = "h-10 rounded-md border border-cream-200 bg-white px-3 text-[14px] outline-none focus:border-emerald-500"

function DetailSheet({ p, onClose, onStatus }: { p: Prospect | null; onClose: () => void; onStatus: (p: Prospect, s: Prospect["status"]) => void }) {
  return (
    <Sheet open={p != null} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto bg-card sm:max-w-md">
        {p && (
          <>
            <SheetHeader>
              <SheetTitle>{p.nama}</SheetTitle>
              <SheetDescription>{p.alamat}</SheetDescription>
            </SheetHeader>
            <div className="space-y-6 px-4 pb-8">
              <div className="flex flex-wrap gap-1.5">
                <Pill>{SOURCE[p.sumber] ?? p.sumber}</Pill>
                {p.telepon && <Pill><Phone className="size-3" /> {p.telepon}</Pill>}
                {p.website && <Pill><Globe className="size-3" /> situs</Pill>}
                {p.sudah_pelanggan && <Pill className="bg-ok-bg text-ok">Sudah pelanggan</Pill>}
              </div>
              <section>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-[13px] font-semibold">Alasan skor</h3>
                  <span className="tabular text-2xl font-[650]">{p.skor}</span>
                </div>
                <ul className="space-y-2">
                  {p.alasan_skor.map((r) => (
                    <li key={r.faktor} className="text-[13px]">
                      <div className="flex justify-between">
                        <span>{r.faktor}</span>
                        <span className="tabular font-medium">+{r.poin}/{r.maks}</span>
                      </div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-cream-200">
                        <div className="h-full rounded-full bg-emerald-500" style={{ width: `${(r.poin / r.maks) * 100}%` }} />
                      </div>
                      <div className="mt-0.5 text-[12px] text-muted-foreground">{r.keterangan}</div>
                    </li>
                  ))}
                </ul>
              </section>
              <section>
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-[13px] font-semibold">Draf pesan pembuka</h3>
                  <VerdictBadge verdict={p.draf_verdict} />
                </div>
                <p className="rounded-lg bg-emerald-100/60 p-3 text-[13px] leading-6">{p.draf_pesan}</p>
                <AButton
                  variant="outline"
                  size="sm"
                  className="mt-2"
                  onClick={() => navigator.clipboard.writeText(p.draf_pesan).then(() => toast.success("Draf disalin — kirim manual oleh staf"))}
                >
                  <Copy className="size-3.5" /> Salin draf
                </AButton>
                <p className="mt-2 text-[12px] text-subtle-foreground">AAGE tidak mengirim pesan massal; staf yang menghubungi prospek.</p>
              </section>
              <section>
                <h3 className="mb-2 text-[13px] font-semibold">Status tindak lanjut</h3>
                <div className="flex flex-wrap gap-2">
                  {(Object.keys(STATUS) as Prospect["status"][]).map((s) => (
                    <button
                      key={s}
                      onClick={() => onStatus(p, s)}
                      className={cn("h-9 rounded-full px-3 text-[13px] font-medium", p.status === s ? "ring-2 ring-emerald-500" : "", STATUS[s].cls)}
                    >
                      {STATUS[s].label}
                    </button>
                  ))}
                </div>
                <p className="mt-2 text-[12px] text-subtle-foreground">Perubahan status tercatat di Ledger dan masuk funnel KPI.</p>
              </section>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

export default function ProspekPage() {
  const [wilayah, setWilayah] = useState("Kota Semarang")
  const [tipe, setTipe] = useState("apotek")
  const [query, setQuery] = useState({ wilayah: "Kota Semarang", tipe: "apotek" })
  const [view, setView] = useState<"tabel" | "peta">("tabel")
  const [loading, setLoading] = useState(false)
  const [meta, setMeta] = useState<{ sumber: string; durasi_ms: number; cache: boolean } | null>(null)
  const [selected, setSelected] = useState<Prospect | null>(null)
  const key = `/api/prospects?wilayah=${encodeURIComponent(query.wilayah)}&tipe=${encodeURIComponent(query.tipe)}`
  const { data, mutate } = useSWR<{ items: Prospect[]; wilayah: string[] }>(key, fetcher)
  const items = useMemo(() => data?.items ?? [], [data])

  async function map() {
    setLoading(true)
    try {
      const res = await api<{ items: Prospect[]; sumber: string; durasi_ms: number; cache: boolean; jumlah: number }>("/api/prospects/search", {
        method: "POST",
        json: { wilayah, tipe },
      })
      setMeta(res)
      setQuery({ wilayah, tipe })
      await mutate({ items: res.items, wilayah: data?.wilayah ?? [] }, { revalidate: false })
      toast.success(`${res.jumlah} prospek dipetakan dari ${SOURCE[res.sumber] ?? res.sumber}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Gagal memetakan prospek")
    } finally {
      setLoading(false)
    }
  }

  async function setStatus(p: Prospect, status: Prospect["status"]) {
    const updated = await api<Prospect>(`/api/prospects/${p.id}`, { method: "PATCH", json: { status } })
    setSelected(updated)
    mutate({ items: items.map((x) => (x.id === p.id ? updated : x)), wilayah: data?.wilayah ?? [] }, { revalidate: false })
  }

  async function exportCsv() {
    const res = await fetch(`/api/prospects/export.csv?wilayah=${encodeURIComponent(query.wilayah)}&tipe=${encodeURIComponent(query.tipe)}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    })
    const blob = await res.blob()
    const a = document.createElement("a")
    a.href = URL.createObjectURL(blob)
    a.download = `prospek-${query.wilayah.replace(/\s+/g, "-").toLowerCase()}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div>
      <PageHeader
        title="Prospek"
        description="Petakan apotek, toko obat, dan minimarket per wilayah. Skor 0–100 dihitung dari aturan transparan; draf pesan pembuka sudah lolos ClaimGuard."
      />
      <GlassCard className="mb-4 flex flex-wrap items-end gap-3 p-4">
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Wilayah (kota/kecamatan)
          <input list="wilayah-list" value={wilayah} onChange={(e) => setWilayah(e.target.value)} className={cn(field, "w-64")} />
          <datalist id="wilayah-list">
            {["Kota Semarang", "Kabupaten Semarang", "Surakarta", "Kudus", "Salatiga", "Demak", "Kendal", ...(data?.wilayah ?? [])].map((w) => (
              <option key={w} value={w} />
            ))}
          </datalist>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Jenis toko
          <select value={tipe} onChange={(e) => setTipe(e.target.value)} className={field}>
            <option value="apotek">Apotek</option>
            <option value="toko obat">Toko obat</option>
            <option value="minimarket">Minimarket</option>
          </select>
        </label>
        <AButton onClick={map} disabled={loading || !wilayah.trim()}>
          {loading ? <LoaderCircle className="size-4 animate-spin" /> : <MapPinned className="size-4" />} Petakan
        </AButton>
        <div className="ml-auto flex items-center gap-2">
          {meta && (
            <span className="text-[12px] text-muted-foreground">
              {SOURCE[meta.sumber]} · {(meta.durasi_ms / 1000).toFixed(1).replace(".", ",")} dtk{meta.cache ? " · cache" : ""}
            </span>
          )}
          <div className="flex rounded-lg bg-cream-100 p-1" role="radiogroup" aria-label="Tampilan">
            {(
              [
                ["tabel", Table2, "Tabel"],
                ["peta", Map, "Peta"],
              ] as const
            ).map(([v, Icon, label]) => (
              <button
                key={v}
                role="radio"
                aria-checked={view === v}
                onClick={() => setView(v)}
                className={cn("inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium", view === v ? "bg-white shadow-xs" : "text-muted-foreground")}
              >
                <Icon className="size-3.5" /> {label}
              </button>
            ))}
          </div>
          <AButton variant="outline" onClick={exportCsv} disabled={!items.length}>
            <Download className="size-4" /> CSV
          </AButton>
        </div>
      </GlassCard>

      {!data ? (
        <SkeletonRows rows={10} />
      ) : items.length === 0 ? (
        <Surface>
          <EmptyState title="Belum ada prospek di wilayah ini" description="Klik Petakan untuk mencari dari Google Places / OpenStreetMap." />
        </Surface>
      ) : view === "peta" ? (
        <Surface className="p-2">
          <ProspectMap items={items} onSelect={setSelected} />
        </Surface>
      ) : (
        <Surface className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="bg-cream-100 text-left text-[12px] tracking-[0.02em] text-muted-foreground">
              <tr>
                <th className="sticky left-0 bg-cream-100 px-3 py-2.5 font-medium">Skor</th>
                <th className="px-3 py-2.5 font-medium">Nama</th>
                <th className="px-3 py-2.5 font-medium">Jarak</th>
                <th className="px-3 py-2.5 font-medium">Rating</th>
                <th className="px-3 py-2.5 font-medium">Kontak</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-3 py-2.5 font-medium">Sumber</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p, i) => (
                <tr key={p.id} onClick={() => setSelected(p)} className={cn("cursor-pointer border-t border-cream-200 hover:bg-emerald-100/40", i % 2 ? "bg-cream-50" : "bg-white")}>
                  <td className={cn("sticky left-0 px-3 py-2.5", i % 2 ? "bg-cream-50" : "bg-white")}>
                    <ScoreBar score={p.skor} reasons={p.alasan_skor} />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="font-medium">{p.nama}</div>
                    <div className="line-clamp-1 text-[12px] text-muted-foreground">{p.alamat}</div>
                  </td>
                  <td className="tabular px-3 py-2.5 whitespace-nowrap">{p.jarak_km != null ? `${p.jarak_km.toLocaleString("id-ID")} km` : "—"}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    {p.rating != null ? (
                      <span className="inline-flex items-center gap-1">
                        <Star className="size-3.5 fill-champagne-600 text-champagne-600" /> {p.rating.toLocaleString("id-ID")}
                        <span className="text-subtle-foreground">({p.jumlah_ulasan})</span>
                      </span>
                    ) : (
                      <span className="text-subtle-foreground">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground">{p.telepon ?? "—"}</td>
                  <td className="px-3 py-2.5">
                    <span className={cn("inline-flex h-6 items-center rounded-full px-2 text-[12px] font-medium", STATUS[p.status].cls)}>{STATUS[p.status].label}</span>
                  </td>
                  <td className="px-3 py-2.5 text-[12px] whitespace-nowrap text-muted-foreground">{SOURCE[p.sumber] ?? p.sumber}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Surface>
      )}
      <DetailSheet p={selected} onClose={() => setSelected(null)} onStatus={setStatus} />
    </div>
  )
}
