"use client"

import { FlaskConical, LoaderCircle } from "lucide-react"
import { useState } from "react"
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { PageHeader, Panel } from "@/components/aage/panel"
import { api, fetcher } from "@/lib/api"
import { formatDateTime, formatDay, formatDuration, formatNum, formatPct, formatRp } from "@/lib/format"
import { useRole } from "@/lib/rbac"
import type { Kpi, Status } from "@/lib/types"
import { cn } from "@/lib/utils"

type EvalHasil = {
  mode: string
  qa: { n: number; akurasi: number; groundedness: number }
  klaim: { n: number; recall: number; precision: number; diblokir_lolos: number }
  eskalasi: { n: number; ketepatan: number }
  negosiasi?: { n: number; sesuai_tier: number }
  pesanan?: { n: number; lengkap: number }
  operasional: { latensi_rata_ms: number; latensi_p95_ms: number; biaya_per_percakapan_rp: number; pesan: number }
}

type EvalSummary = {
  ada: boolean
  hasil: EvalHasil | null
  dijalankan_pada: string | null
  berjalan: boolean
  mulai: string | null
  error: string | null
}

type Nilai = { teks: string; lolos: boolean; sumber: "uji" | "live" } | null
type Ctx = { kpi?: Kpi; status?: Status; ev?: EvalHasil | null }

const pct = (v: number) => `${String(v).replace(".", ",")}%`

// Brief §9 — kriteria penerimaan (target awal, ditinjau setelah baseline Nov 2026).
const TARGETS: { metrik: string; target: string; nilai: (c: Ctx) => Nilai }[] = [
  {
    metrik: "Akurasi jawaban katalog",
    target: "≥95% (≥200 pertanyaan berlabel)",
    nilai: ({ ev }) => (ev ? { teks: `${pct(ev.qa.akurasi)} · n=${ev.qa.n}`, lolos: ev.qa.akurasi >= 95 && ev.qa.n >= 200, sumber: "uji" } : null),
  },
  {
    metrik: "Groundedness jawaban otomatis",
    target: "≥98%",
    nilai: ({ ev }) => (ev ? { teks: pct(ev.qa.groundedness), lolos: ev.qa.groundedness >= 98, sumber: "uji" } : null),
  },
  {
    metrik: "ClaimGuard",
    target: "Recall ≥90%, precision ≥80% (≥100 kalimat)",
    nilai: ({ ev }) =>
      ev
        ? {
            teks: `R ${pct(ev.klaim.recall)} · P ${pct(ev.klaim.precision)} · n=${ev.klaim.n}`,
            lolos: ev.klaim.recall >= 90 && ev.klaim.precision >= 80 && ev.klaim.n >= 100,
            sumber: "uji",
          }
        : null,
  },
  {
    metrik: "Klaim berisiko terbit tanpa approval",
    target: "0 kejadian",
    nilai: ({ ev }) => (ev ? { teks: `${ev.klaim.diblokir_lolos} kejadian`, lolos: ev.klaim.diblokir_lolos === 0, sumber: "uji" } : null),
  },
  {
    metrik: "Ketepatan eskalasi",
    target: "≥95%",
    nilai: ({ ev }) => (ev ? { teks: `${pct(ev.eskalasi.ketepatan)} · n=${ev.eskalasi.n}`, lolos: ev.eskalasi.ketepatan >= 95, sumber: "uji" } : null),
  },
  {
    metrik: "Latensi respons asisten (p95)",
    target: "≤10 detik",
    nilai: ({ kpi }) =>
      kpi?.ringkasan.respons_ai_p95_ms == null
        ? null
        : { teks: formatDuration(kpi.ringkasan.respons_ai_p95_ms), lolos: kpi.ringkasan.respons_ai_p95_ms <= 10_000, sumber: "live" },
  },
  { metrik: "Waktu tugas rutin", target: "Turun ≥30% dari baseline", nilai: () => null },
  { metrik: "Kegunaan (SUS)", target: "≥68", nilai: () => null },
  {
    metrik: "Biaya AI per percakapan",
    target: "Dalam anggaran bulanan",
    nilai: ({ kpi, status }) =>
      kpi && status
        ? {
            teks: formatRp(kpi.ringkasan.biaya_per_percakapan_rp, { decimals: true }),
            lolos: status.anggaran.terpakai_bulan_ini_rp <= status.anggaran.bulanan_rp,
            sumber: "live",
          }
        : null,
  },
]

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Panel className="p-5">
      <div className="text-[13px] text-muted-foreground">{label}</div>
      <div className="tabular mt-2 text-[26px] leading-8 font-semibold tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-[12px] text-subtle-foreground">{hint}</div>}
    </Panel>
  )
}

function CostChart({ data }: { data: Kpi["harian"] }) {
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 4, left: -12, bottom: 0 }}>
          <defs>
            <linearGradient id="eval-cost" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--brand-500)" stopOpacity={0.18} />
              <stop offset="100%" stopColor="var(--brand-500)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
          <XAxis dataKey="tanggal" tickFormatter={(v) => formatDay(v)} tickLine={false} axisLine={false} tick={{ fill: "var(--chart-axis)", fontSize: 11 }} />
          <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--chart-axis)", fontSize: 11 }} tickFormatter={(v) => `Rp${formatNum(v)}`} />
          <Tooltip
            cursor={{ stroke: "var(--line)" }}
            content={({ active, payload, label }) =>
              active && payload?.length ? (
                <div className="glass !rounded-[10px] px-3 py-2 text-[12px]">
                  <div className="text-muted-foreground">{formatDay(String(label))}</div>
                  <div className="tabular font-semibold">{formatRp(Number(payload[0].value), { decimals: true })} / percakapan</div>
                </div>
              ) : null
            }
          />
          <Area type="monotone" dataKey="biaya_per_percakapan_rp" stroke="var(--brand-500)" strokeWidth={2} fill="url(#eval-cost)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function EvalRunner({ summary, onStarted }: { summary?: EvalSummary; onStarted: () => void }) {
  const { role } = useRole()
  const [starting, setStarting] = useState(false)
  const running = summary?.berjalan || starting

  async function start() {
    setStarting(true)
    try {
      await api("/api/eval/run", { method: "POST" })
      toast.success("Evaluasi dimulai — hasil diperbarui otomatis saat selesai")
      onStarted()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setStarting(false)
    }
  }

  return (
    <Panel className="flex flex-wrap items-center gap-x-5 gap-y-3 p-5">
      <FlaskConical className="size-5 shrink-0 text-forest-700" />
      <div className="min-w-0 flex-1 text-[13px]">
        <div className="font-medium">Dataset uji berlabel</div>
        <div className="text-muted-foreground">
          {summary?.ada && summary.hasil
            ? `Terakhir dijalankan ${formatDateTime(summary.dijalankan_pada)} · mode ${summary.hasil.mode} · ${formatNum(summary.hasil.operasional.pesan)} pesan diuji`
            : "Belum ada hasil uji."}
        </div>
        {summary?.error && <div className="text-blocked">Evaluasi terakhir gagal: {summary.error}</div>}
      </div>
      {role === "admin" && (
        <AButton size="sm" onClick={start} disabled={running}>
          {running ? <LoaderCircle className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
          {running ? "Sedang berjalan…" : "Jalankan evaluasi"}
        </AButton>
      )}
    </Panel>
  )
}

export default function EvaluasiPage() {
  const { data: kpi } = useSWR<Kpi>("/api/kpi", fetcher, { refreshInterval: 30000 })
  const { data: status } = useSWR<Status>("/api/status", fetcher, { refreshInterval: 30000 })
  const { data: summary, mutate } = useSWR<EvalSummary>("/api/eval/summary", fetcher, {
    refreshInterval: (d) => (d?.berjalan ? 2000 : 30000),
  })
  const r = kpi?.ringkasan
  const ctx: Ctx = { kpi, status, ev: summary?.hasil }

  return (
    <div className="space-y-5">
      <PageHeader
        title="Evaluasi & Biaya"
        description="Hasil dataset uji berlabel dan pemakaian biaya AI. Target adalah kriteria awal Brief §9 dan ditinjau ulang setelah baseline November 2026."
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Biaya AI bulan ini" value={formatRp(status?.anggaran.terpakai_bulan_ini_rp, { decimals: true })} hint={status ? `dari batas ${formatRp(status.anggaran.bulanan_rp)}` : undefined} />
        <Stat label="Biaya / percakapan" value={formatRp(r?.biaya_per_percakapan_rp, { decimals: true })} hint="rata-rata 14 hari" />
        <Stat label="Respons AI p95" value={formatDuration(r?.respons_ai_p95_ms)} hint="target ≤10 detik" />
        <Stat label="Dijawab otomatis" value={formatPct(r?.otomatis_persen)} hint={r ? `${formatPct(r.eskalasi_persen)} dieskalasi` : undefined} />
      </div>

      <EvalRunner summary={summary} onStarted={() => mutate()} />

      <Panel className="overflow-hidden">
        <div className="flex items-baseline justify-between gap-3 p-5 pb-3">
          <h2 className="text-[14px] font-semibold">Target uji</h2>
          <span className="text-[12px] text-subtle-foreground">Uji = dataset berlabel · Live = data operasional</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="border-y border-line bg-canvas text-left text-[12px] text-muted-foreground">
              <tr>
                <th className="px-5 py-2.5 font-medium">Metrik</th>
                <th className="px-3 py-2.5 font-medium">Target awal</th>
                <th className="px-3 py-2.5 font-medium">Terkini</th>
                <th className="px-5 py-2.5 text-right font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {TARGETS.map((t) => {
                const v = t.nilai(ctx)
                return (
                  <tr key={t.metrik} className="border-b border-line last:border-0">
                    <td className="px-5 py-3 font-medium">{t.metrik}</td>
                    <td className="px-3 py-3 text-muted-foreground">{t.target}</td>
                    <td className="tabular px-3 py-3 whitespace-nowrap">
                      {v ? (
                        <>
                          {v.teks}
                          <span className="ml-2 rounded-full bg-soft px-1.5 py-0.5 text-[10.5px] font-medium text-muted-foreground uppercase">{v.sumber}</span>
                        </>
                      ) : (
                        <span className="text-subtle-foreground">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <span
                        className={cn(
                          "inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium whitespace-nowrap",
                          !v ? "bg-soft text-muted-foreground" : v.lolos ? "bg-ok-bg text-ok" : "bg-review-bg text-review",
                        )}
                      >
                        <span className={cn("size-1.5 rounded-full", !v ? "bg-subtle-foreground" : v.lolos ? "bg-ok" : "bg-review")} />
                        {!v ? "Belum diukur" : v.lolos ? "Memenuhi" : "Di bawah target"}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="border-t border-line px-5 py-3 text-[12px] text-subtle-foreground">
          Waktu tugas rutin dan SUS diukur lewat sesi uji pengguna bersama mitra, bukan otomatis.
          {summary?.hasil?.mode?.startsWith("offline") && " Hasil uji saat ini dari mode offline deterministik (tanpa LLM)."}
        </p>
      </Panel>

      <Panel className="p-5">
        <div className="mb-4 flex items-baseline justify-between gap-3">
          <h2 className="text-[14px] font-semibold">Biaya per percakapan</h2>
          <span className="text-[12px] text-subtle-foreground">14 hari terakhir</span>
        </div>
        {kpi ? <CostChart data={kpi.harian} /> : <div className="shimmer h-56 rounded-lg" />}
      </Panel>
    </div>
  )
}
