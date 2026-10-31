"use client"

// Drawer detail prospek dengan 3 tab: Informasi Dasar · Live AI Search Audit · Next Best Action.

import { Compass, Copy, ExternalLink, Globe2, Info, LoaderCircle, MapPin, MessageCircle, Newspaper, PlugZap, RefreshCw, Send, Sparkles } from "lucide-react"
import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { ApiError, api } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import type { Prospect } from "@/lib/types"
import { cn } from "@/lib/utils"

import { AButton } from "./button"
import { Pill, VerdictBadge } from "./status"

export const STATUS: Record<Prospect["status"], { label: string; cls: string }> = {
  baru: { label: "Baru", cls: "bg-soft text-muted-foreground" },
  dihubungi: { label: "Dihubungi", cls: "bg-info-bg text-info" },
  merespons: { label: "Merespons", cls: "bg-ok-bg text-ok" },
  pelanggan: { label: "Pelanggan", cls: "bg-brand-50 text-forest-700" },
  menolak: { label: "Menolak", cls: "bg-blocked-bg text-blocked" },
}

/** wa.me hanya membuka WhatsApp staf dengan draf terisi — staf yang menekan Kirim (bukan pesan massal). */
export function waLink(p: Prospect): string | null {
  return p.wa ? `https://wa.me/${p.wa}?text=${encodeURIComponent(p.draf_pesan)}` : null
}

function toLocalInput(iso: string | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function FollowUp({ p, onUpdated }: { p: Prospect; onUpdated: (p: Prospect) => void }) {
  const [catatan, setCatatan] = useState(p.catatan ?? "")
  const [pic, setPic] = useState(p.pic ?? "")
  const [tanggal, setTanggal] = useState(toLocalInput(p.tindak_lanjut_pada))
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    setCatatan(p.catatan ?? "")
    setPic(p.pic ?? "")
    setTanggal(toLocalInput(p.tindak_lanjut_pada))
  }, [p.id, p.catatan, p.pic, p.tindak_lanjut_pada])

  async function save() {
    setBusy(true)
    try {
      const updated = await api<Prospect>(`/api/prospects/${p.id}`, {
        method: "PATCH",
        json: { catatan: catatan || null, pic: pic || null, tindak_lanjut_pada: tanggal ? new Date(tanggal).toISOString() : null },
      })
      onUpdated(updated)
      toast.success("Rencana tindak lanjut disimpan")
    } catch {
      toast.error("Gagal menyimpan tindak lanjut")
    } finally {
      setBusy(false)
    }
  }

  const input = "mt-0.5 h-9 w-full rounded-md border border-line bg-white px-2 text-[13px] outline-none focus:border-brand-500"
  return (
    <section>
      <h3 className="mb-2 text-[13px] font-semibold">Rencana tindak lanjut</h3>
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="text-[12px] text-muted-foreground">
          PIC sales
          <input value={pic} onChange={(e) => setPic(e.target.value)} className={input} placeholder="Nama staf" />
        </label>
        <label className="text-[12px] text-muted-foreground">
          Tindak lanjut pada
          <input type="datetime-local" value={tanggal} onChange={(e) => setTanggal(e.target.value)} className={input} />
        </label>
      </div>
      <label className="mt-2 block text-[12px] text-muted-foreground">
        Catatan kunjungan / percakapan
        <textarea
          value={catatan}
          onChange={(e) => setCatatan(e.target.value)}
          rows={3}
          className="mt-0.5 w-full rounded-md border border-line bg-white p-2 text-[13px] outline-none focus:border-brand-500"
          placeholder="Mis. pemilik minta katalog, datang lagi Kamis"
        />
      </label>
      <AButton size="sm" className="mt-2" disabled={busy} onClick={save}>
        Simpan tindak lanjut
      </AButton>
    </section>
  )
}

type Tab = "dasar" | "market" | "nba"
const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "dasar", label: "Informasi Dasar", icon: <Info className="size-3.5" /> },
  { id: "market", label: "Live AI Search Audit", icon: <Globe2 className="size-3.5" /> },
  { id: "nba", label: "Next Best Action", icon: <Compass className="size-3.5" /> },
]

function TabsHeader({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  return (
    <div
      role="tablist"
      aria-label="Detail prospek"
      className="grid grid-cols-3 gap-1 rounded-xl border border-white/10 bg-zinc-900/85 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_8px_20px_-10px_rgba(0,0,0,0.5)] backdrop-blur-md"
    >
      {TABS.map((t) => {
        const on = active === t.id
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={on}
            onClick={() => onChange(t.id)}
            className={cn(
              "relative flex min-h-9 items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-center text-[12px] leading-tight font-semibold transition-colors",
              on
                ? "bg-emerald-500/15 text-emerald-300 shadow-[inset_0_0_0_1px_rgba(16,185,129,0.45),0_0_14px_-4px_rgba(16,185,129,0.7)]"
                : "text-zinc-400 hover:bg-white/5 hover:text-zinc-100",
            )}
          >
            {t.icon}
            <span>{t.label}</span>
            {on && <span className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-brand-500" aria-hidden />}
          </button>
        )
      })}
    </div>
  )
}

function StatusButtons({ p, onStatus }: { p: Prospect; onStatus: (p: Prospect, s: Prospect["status"]) => void }) {
  return (
    <section>
      <h3 className="mb-2 text-[13px] font-semibold">Status tindak lanjut</h3>
      <div className="flex flex-wrap gap-2">
        {(Object.keys(STATUS) as Prospect["status"][]).map((s) => (
          <button
            key={s}
            onClick={() => onStatus(p, s)}
            className={cn("h-9 rounded-full px-3 text-[13px] font-medium", p.status === s && "ring-2 ring-brand-500", STATUS[s].cls)}
          >
            {STATUS[s].label}
          </button>
        ))}
      </div>
      <p className="mt-2 text-[12px] text-subtle-foreground">Perubahan status tercatat di Ledger dan masuk funnel KPI.</p>
    </section>
  )
}

function TabDasar({ p, onStatus, onUpdated }: { p: Prospect; onStatus: (p: Prospect, s: Prospect["status"]) => void; onUpdated: (p: Prospect) => void }) {
  const link = waLink(p)
  return (
    <div className="space-y-6">
      {p.conversation_id && (
        <Link href={`/inbox?id=${p.conversation_id}`} className="flex items-center gap-2 rounded-md bg-ok-bg px-3 py-2 text-[13px] font-medium text-ok">
          <MessageCircle className="size-4" /> Prospek ini sudah chat lewat WhatsApp — buka percakapan
        </Link>
      )}
      <section>
        <div className="mb-2 flex items-end justify-between">
          <h3 className="text-[13px] font-semibold">Opportunity Score</h3>
          <span className="tabular text-[28px] leading-none font-semibold text-forest-900">{p.skor}</span>
        </div>
        <ul className="space-y-2.5">
          {p.alasan_skor.map((r) => (
            <li key={r.faktor} className="text-[13px]">
              <div className="flex justify-between">
                <span>{r.faktor}</span>
                <span className={cn("tabular font-medium", r.poin < 0 && "text-blocked")}>
                  {r.poin < 0 ? r.poin.toLocaleString("id-ID") : `+${r.poin.toLocaleString("id-ID")}/${r.maks}`}
                </span>
              </div>
              {r.maks > 0 && (
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-line">
                  <div className="h-full rounded-full bg-brand-500" style={{ width: `${(r.poin / r.maks) * 100}%` }} />
                </div>
              )}
              <div className="mt-0.5 text-[12px] text-muted-foreground">{r.keterangan}</div>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[12px] text-subtle-foreground">
          Dipindai {formatDateTime(p.terakhir_dipindai)} · data OpenStreetMap apa adanya (tidak dilengkapi tebakan).
        </p>
      </section>
      <section>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[13px] font-semibold">Draf pesan pembuka WhatsApp</h3>
          <VerdictBadge verdict={p.draf_verdict} />
        </div>
        <p className="rounded-lg bg-brand-50 p-3 text-[13px] leading-6">{p.draf_pesan}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {link ? (
            <a
              href={link}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => p.status === "baru" && onStatus(p, "dihubungi")}
              className="btn-liquid inline-flex h-8 items-center gap-1.5 rounded-[10px] px-3 text-[13px] font-medium"
            >
              <Send className="size-3.5" /> Buka di WhatsApp
            </a>
          ) : (
            <span className="text-[12px] text-subtle-foreground">Tidak ada nomor di OSM — kunjungi langsung atau cari nomor toko.</span>
          )}
          <AButton
            variant="outline"
            size="sm"
            onClick={() => navigator.clipboard.writeText(p.draf_pesan).then(() => toast.success("Draf disalin — kirim manual oleh staf"))}
          >
            <Copy className="size-3.5" /> Salin draf
          </AButton>
        </div>
        {link && <p className="mt-1 text-[12px] text-subtle-foreground">WhatsApp staf terbuka dengan draf terisi; status otomatis jadi “Dihubungi”.</p>}
      </section>
      <StatusButtons p={p} onStatus={onStatus} />
      <FollowUp p={p} onUpdated={onUpdated} />
    </div>
  )
}

function RunButton({ busy, onRun, label }: { busy: boolean; onRun: () => void; label: string }) {
  return (
    <AButton onClick={onRun} disabled={busy} size="sm">
      {busy ? <LoaderCircle className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />} {label}
    </AButton>
  )
}

function TabMarket({ p, busy, onRun }: { p: Prospect; busy: boolean; onRun: () => void }) {
  const m = p.market_analysis
  if (!m) {
    return (
      <div className="space-y-3 rounded-xl border border-line p-4 text-[13px]">
        <p className="text-muted-foreground">
          Audit mencari berita Google 7 hari terakhir tentang topik kesehatan di {p.wilayah} (pencernaan, daya tahan tubuh, batuk, stamina)
          untuk membaca kebutuhan pasar sekitar toko ini.
        </p>
        <RunButton busy={busy} onRun={onRun} label="Jalankan audit" />
      </div>
    )
  }
  if (m.status !== "ok") {
    return (
      <div className="space-y-3">
        <div className="flex items-start gap-2 rounded-xl border border-review/30 bg-review-bg p-4 text-[13px] text-review">
          <PlugZap className="mt-0.5 size-4 shrink-0" />
          <div>
            <p className="font-semibold">{m.status === "tidak_terhubung" ? "Live AI Search belum terhubung" : "Pencarian gagal"}</p>
            <p className="mt-0.5">{m.ringkasan}</p>
          </div>
        </div>
        <RunButton busy={busy} onRun={onRun} label="Coba lagi" />
      </div>
    )
  }
  const max = Math.max(1, ...m.topik.map((t) => t.jumlah_artikel))
  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-line bg-soft/60 p-4">
        <div className="mb-1 flex items-center justify-between text-[11.5px] text-subtle-foreground">
          <span>{m.sumber} · {m.periode}</span>
          <span>{formatDateTime(m.dipindai)}</span>
        </div>
        <p className="text-[13.5px] leading-6">{m.ringkasan}</p>
      </div>
      <section>
        <h3 className="mb-2 text-[13px] font-semibold">Jumlah berita per topik</h3>
        <ul className="space-y-2">
          {m.topik.map((t) => (
            <li key={t.id} className="text-[12.5px]">
              <div className="flex justify-between">
                <span className={cn(t.id === m.topik_utama && "font-semibold text-forest-900")}>{t.label}</span>
                <span className="tabular">{t.jumlah_artikel} artikel</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-line">
                <div className={cn("h-full rounded-full", t.id === m.topik_utama ? "bg-brand-500" : "bg-brand-300")} style={{ width: `${(t.jumlah_artikel / max) * 100}%` }} />
              </div>
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h3 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold"><Newspaper className="size-4" /> Artikel sumber</h3>
        <ul className="space-y-2">
          {m.topik
            .flatMap((t) => t.artikel.map((a) => ({ ...a, topik: t.label })))
            .slice(0, 12)
            .map((a) => (
              <li key={a.tautan}>
                <a href={a.tautan} target="_blank" rel="noopener noreferrer" className="group block rounded-lg border border-line p-3 hover:border-brand-300 hover:bg-brand-50/50">
                  <div className="flex items-start gap-2">
                    <span className="min-w-0 flex-1 text-[13px] font-medium group-hover:text-forest-700">{a.judul}</span>
                    <ExternalLink className="mt-0.5 size-3.5 shrink-0 text-subtle-foreground" />
                  </div>
                  {a.cuplikan && <p className="mt-1 line-clamp-2 text-[12px] text-muted-foreground">{a.cuplikan}</p>}
                  <p className="mt-1 text-[11px] text-subtle-foreground">{[a.sumber, a.tanggal, a.topik].filter(Boolean).join(" · ")}</p>
                </a>
              </li>
            ))}
        </ul>
        {m.topik.every((t) => t.artikel.length === 0) && <p className="text-[12.5px] text-muted-foreground">Tidak ada artikel dalam periode ini.</p>}
      </section>
      <RunButton busy={busy} onRun={onRun} label="Perbarui audit" />
    </div>
  )
}

function TabNba({ p, busy, onRun, onStatus }: { p: Prospect; busy: boolean; onRun: () => void; onStatus: (p: Prospect, s: Prospect["status"]) => void }) {
  const n = p.nba
  return (
    <div className="space-y-6">
      {!n ? (
        <div className="space-y-3 rounded-xl border border-line p-4 text-[13px]">
          <p className="text-muted-foreground">NBA dirumuskan dari sinyal berita, Opportunity Score, kontak, status, katalog berklaim resmi, dan kebijakan penjualan.</p>
          <RunButton busy={busy} onRun={onRun} label="Rumuskan NBA" />
        </div>
      ) : (
        <section className="space-y-4">
          <div className="rounded-xl bg-zinc-950">
          <div className="rounded-xl border border-emerald-500/40 bg-emerald-950/40 p-5 shadow-inner shadow-[inset_0_0_24px_rgba(16,185,129,0.12),0_0_28px_-10px_rgba(16,185,129,0.55)]">
            <div className="mb-2 flex items-center gap-2">
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-bold tracking-wide text-emerald-300">
                <Sparkles className="size-3" /> PRIORITAS {n.prioritas}
              </span>
              <span className="text-[11px] text-emerald-200/80">{n.topik}</span>
              <span className="ml-auto">
                <VerdictBadge verdict={n.verdict} rules={n.aturan} />
              </span>
            </div>
            <p className="text-[13.5px] leading-6 text-emerald-50">{n.teks}</p>
          </div>
          </div>
          <div>
            <h3 className="mb-2 text-[13px] font-semibold">Produk yang ditawarkan</h3>
            <ul className="space-y-2">
              {n.produk.map((x) => (
                <li key={x.sku} className="rounded-lg border border-line p-3 text-[12.5px]">
                  <div className="flex justify-between gap-2">
                    <span className="font-medium">{x.nama}</span>
                    <span className="font-mono text-[11px] text-subtle-foreground">{x.izin_edar}</span>
                  </div>
                  <p className="mt-0.5 text-muted-foreground">Klaim resmi: {x.klaim_resmi}</p>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mb-2 text-[13px] font-semibold">Dasar rekomendasi</h3>
            <ul className="list-disc space-y-1 pl-5 text-[12.5px] text-muted-foreground">
              {n.dasar.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
            <p className="mt-2 text-[11px] text-subtle-foreground">{n.metode} · {formatDateTime(n.dirumuskan)}</p>
          </div>
          <RunButton busy={busy} onRun={onRun} label="Rumuskan ulang" />
        </section>
      )}
      <StatusButtons p={p} onStatus={onStatus} />
    </div>
  )
}

export function ProspectDrawer({
  p,
  onClose,
  onStatus,
  onUpdated,
}: {
  p: Prospect | null
  onClose: () => void
  onStatus: (p: Prospect, s: Prospect["status"]) => void
  onUpdated: (p: Prospect) => void
}) {
  const [activeTab, setActiveTab] = useState<"dasar" | "market" | "nba">("dasar")
  const [busy, setBusy] = useState(false)
  const id = p?.id
  useEffect(() => {
    setActiveTab("dasar")
  }, [id])

  async function runResearch() {
    if (!p) return
    setBusy(true)
    try {
      const updated = await api<Prospect>(`/api/prospects/${p.id}/riset`, { method: "POST" })
      onUpdated(updated)
      if (updated.market_analysis?.status === "ok") toast.success("Audit pasar & NBA diperbarui")
      else toast("NBA dirumuskan dari data internal — Live AI Search belum terhubung")
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Riset gagal")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet open={p != null} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto bg-card data-[side=right]:sm:max-w-xl">
        {p && (
          <>
            <SheetHeader className="space-y-3">
              <div>
                <SheetTitle>{p.nama}</SheetTitle>
                <SheetDescription>{p.alamat}</SheetDescription>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Pill>{p.tipe}</Pill>
                <Pill>{p.jarak_km != null ? `${p.jarak_km.toLocaleString("id-ID")} km` : "—"}</Pill>
                {p.osm_id && (
                  <a
                    href={`https://www.openstreetmap.org/${p.osm_id.replace("osm:", "")}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex h-6 items-center gap-1 rounded-full bg-brand-50 px-2 text-[12px] font-medium text-forest-700 hover:underline"
                  >
                    <MapPin className="size-3" /> {p.osm_id.replace("osm:", "OSM ")}
                  </a>
                )}
                {p.sudah_pelanggan && <Pill className="bg-ok-bg text-ok">Sudah pelanggan</Pill>}
                {p.jaringan && <Pill className="bg-review-bg text-review">Jaringan {p.jaringan}</Pill>}
              </div>
              <TabsHeader active={activeTab} onChange={setActiveTab} />
            </SheetHeader>
            <div className="px-4 pb-8">
              {activeTab === "dasar" && <TabDasar p={p} onStatus={onStatus} onUpdated={onUpdated} />}
              {activeTab === "market" && <TabMarket p={p} busy={busy} onRun={runResearch} />}
              {activeTab === "nba" && <TabNba p={p} busy={busy} onRun={runResearch} onStatus={onStatus} />}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}
