"use client"

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import useSWR from "swr"

import { PageHeader, Panel } from "@/components/aage/panel"
import { fetcher } from "@/lib/api"
import { formatDay, formatDuration, formatNum, formatPct, formatRp } from "@/lib/format"
import type { Kpi, Status } from "@/lib/types"
import { cn } from "@/lib/utils"

type Target = {
  metrik: string
  target: string
  /** Nilai terkini bila sudah bisa diukur dari API; null = menunggu dataset uji. */
  nilai?: (k: Kpi, s: Status | undefined) => { teks: string; lolos: boolean } | null
}

// Brief §9 — kriteria penerimaan (target awal, ditinjau setelah baseline Nov 2026).
const TARGETS: Target[] = [
  { metrik: "Akurasi jawaban katalog", target: "≥95% (≥200 pertanyaan berlabel)" },
  { metrik: "Groundedness jawaban otomatis", target: "≥98%" },
  { metrik: "ClaimGuard", target: "Recall ≥90%, precision ≥80% (≥100 kalimat)" },
  { metrik: "Klaim berisiko terbit tanpa approval", target: "0 kejadian" },
  { metrik: "Ketepatan eskalasi", target: "≥95%" },
  {
    metrik: "Latensi respons asisten (p95)",
    target: "≤10 detik",
    nilai: (k) => (k.ringkasan.respons_ai_p95_ms == null ? null : { teks: formatDuration(k.ringkasan.respons_ai_p95_ms), lolos: k.ringkasan.respons_ai_p95_ms <= 10_000 }),
  },
  { metrik: "Waktu tugas rutin", target: "Turun ≥30% dari baseline" },
  { metrik: "Kegunaan (SUS)", target: "≥68" },
  {
    metrik: "Biaya AI per percakapan",
    target: "Dalam anggaran bulanan",
    nilai: (k, s) => (s ? { teks: formatRp(k.ringkasan.biaya_per_percakapan_rp, { decimals: true }), lolos: s.anggaran.terpakai_bulan_ini_rp <= s.anggaran.bulanan_rp } : null),
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

export default function EvaluasiPage() {
  const { data: kpi } = useSWR<Kpi>("/api/kpi", fetcher, { refreshInterval: 30000 })
  const { data: status } = useSWR<Status>("/api/status", fetcher, { refreshInterval: 30000 })
  const r = kpi?.ringkasan

  return (
    <div className="space-y-5">
      <PageHeader
        title="Evaluasi & Biaya"
        description="Target uji purwarupa dan pemakaian biaya AI. Angka adalah target awal dan ditinjau ulang setelah baseline November 2026."
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Biaya AI bulan ini" value={formatRp(status?.anggaran.terpakai_bulan_ini_rp, { decimals: true })} hint={status ? `dari batas ${formatRp(status.anggaran.bulanan_rp)}` : undefined} />
        <Stat label="Biaya / percakapan" value={formatRp(r?.biaya_per_percakapan_rp, { decimals: true })} hint="rata-rata 14 hari" />
        <Stat label="Respons AI p95" value={formatDuration(r?.respons_ai_p95_ms)} hint="target ≤10 detik" />
        <Stat label="Dijawab otomatis" value={formatPct(r?.otomatis_persen)} hint={r ? `${formatPct(r.eskalasi_persen)} dieskalasi` : undefined} />
      </div>

      <Panel className="p-5">
        <div className="mb-4 flex items-baseline justify-between gap-3">
          <h2 className="text-[14px] font-semibold">Biaya per percakapan</h2>
          <span className="text-[12px] text-subtle-foreground">14 hari terakhir</span>
        </div>
        {kpi ? <CostChart data={kpi.harian} /> : <div className="shimmer h-56 rounded-lg" />}
      </Panel>

      <Panel className="overflow-hidden">
        <div className="flex items-baseline justify-between gap-3 p-5 pb-3">
          <h2 className="text-[14px] font-semibold">Target uji</h2>
          <span className="text-[12px] text-subtle-foreground">Kriteria penerimaan, bukan hasil</span>
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
                const v = kpi && t.nilai ? t.nilai(kpi, status) : null
                return (
                  <tr key={t.metrik} className="border-b border-line last:border-0">
                    <td className="px-5 py-3 font-medium">{t.metrik}</td>
                    <td className="px-3 py-3 text-muted-foreground">{t.target}</td>
                    <td className="tabular px-3 py-3">{v ? v.teks : <span className="text-subtle-foreground">—</span>}</td>
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
          Metrik akurasi, groundedness, ClaimGuard, dan eskalasi terisi setelah dataset uji berlabel dijalankan oleh agen Evaluation.
        </p>
      </Panel>
    </div>
  )
}
