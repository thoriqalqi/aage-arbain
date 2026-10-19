"use client"

import { BarChart3, Bot, CalendarDays, ClipboardCheck, Coins, Download, Filter, MessagesSquare, ShieldX, TrendingUp, Users } from "lucide-react"
import Link from "next/link"
import { motion } from "motion/react"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { DeltaPill, FunnelChart, KpiTile, VolumeChart, WeekBars } from "@/components/aage/charts"
import { EmptyState, SkeletonRows } from "@/components/aage/empty-state"
import { CardHeader, PageHeader, Panel } from "@/components/aage/panel"
import { Pill, VerdictBadge } from "@/components/aage/status"
import { fetcher } from "@/lib/api"
import { contactName, formatDay, formatDuration, formatNum, formatPct, formatRp, relativeTime } from "@/lib/format"
import { INTENT_LABEL, type Approval, type Kpi } from "@/lib/types"

const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.04 } } }
const item = { hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0, transition: { duration: 0.24, ease: [0.22, 1, 0.36, 1] as const } } }

export default function RingkasanPage() {
  const { data: kpi } = useSWR<Kpi>("/api/kpi", fetcher, { refreshInterval: 15000 })
  const { data: ap } = useSWR<{ items: Approval[] }>("/api/approvals?status=menunggu", fetcher, { refreshInterval: 8000 })
  const r = kpi?.ringkasan
  const days = kpi?.harian ?? []
  const last7 = days.slice(-7)
  const prev7 = days.slice(-14, -7)
  const sum = (a: { pesan: number }[]) => a.reduce((s, d) => s + d.pesan, 0)
  const totalPesan = sum(days)
  const week = sum(last7)
  const weekDelta = week - sum(prev7)
  const range = days.length ? `${formatDay(days[0].tanggal)} – ${formatDay(days[days.length - 1].tanggal)}` : "14 hari"

  function exportCsv() {
    if (!kpi) return
    const rows = [["tanggal", "chat", "pesan", "otomatis", "eskalasi", "diblokir"], ...kpi.harian.map((d) => [d.tanggal, d.chat, d.pesan, d.otomatis, d.eskalasi, d.diblokir])]
    const a = document.createElement("a")
    a.href = URL.createObjectURL(new Blob([rows.map((x) => x.join(",")).join("\n")], { type: "text/csv" }))
    a.download = "kpi-aage.csv"
    a.click()
  }

  return (
    <motion.div variants={stagger} initial="hidden" animate="show" className="space-y-5">
      <motion.div variants={item}>
        <PageHeader
          title="Ringkasan"
          actions={
            <>
              <span className="btn-glass inline-flex h-8 items-center gap-1.5 rounded-[10px] px-3 text-[13px] font-medium">
                <CalendarDays className="size-4 text-muted-foreground" /> {range}
              </span>
              <Link href="/ledger" className="btn-glass inline-flex h-8 items-center gap-1.5 rounded-[10px] px-3 text-[13px] font-medium">
                <Filter className="size-4 text-muted-foreground" /> Ledger
              </Link>
              <AButton size="sm" onClick={exportCsv} disabled={!kpi}>
                <Download className="size-4" /> Ekspor
              </AButton>
            </>
          }
        />
      </motion.div>

      <motion.div variants={item} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {r ? (
          <>
            <KpiTile label="Chat 14 hari" value={r.chat} delta={kpi?.delta.chat} hint={`${formatNum(r.pesan_masuk)} pesan masuk`}
              icon={<MessagesSquare />} info="Jumlah percakapan unik dengan pesan masuk dalam periode." />
            <KpiTile label="Dijawab otomatis" value={r.otomatis_persen} format={formatPct} delta={kpi?.delta.otomatis_persen} deltaFormat={formatPct}
              hint={`Respons AI p95 ${formatDuration(r.respons_ai_p95_ms)}`} icon={<Bot />} info="Persentase keputusan kebijakan 'kirim' tanpa staf." />
            <KpiTile label="Klaim diblokir" value={r.klaim_diblokir} delta={kpi?.delta.klaim_diblokir} deltaGoodWhenUp={false}
              hint={`${r.klaim_ditahan} draf ditahan untuk review`} icon={<ShieldX />} info="Klaim terapi yang dihentikan ClaimGuard (masuk & keluar)." />
            <KpiTile label="Biaya AI / percakapan" value={r.biaya_per_percakapan_rp} format={(v) => formatRp(v, { decimals: true })}
              delta={kpi?.delta.biaya_per_percakapan_rp} deltaGoodWhenUp={false} deltaFormat={(v) => formatRp(v, { decimals: true })}
              hint={`Total ${formatRp(r.biaya_total_rp, { decimals: true })}`} icon={<Coins />} info="Total biaya LLM dibagi jumlah percakapan." />
          </>
        ) : (
          Array.from({ length: 4 }).map((_, i) => <div key={i} className="shimmer h-[132px] rounded-[14px]" />)
        )}
      </motion.div>

      <motion.div variants={item} className="grid gap-4 lg:grid-cols-3">
        <Panel className="p-5 lg:col-span-2">
          <CardHeader icon={<BarChart3 />} title="Volume chat" aside={<Pill>{range}</Pill>} />
          <div className="mt-4 mb-5">
            <div className="tabular text-[28px] leading-9 font-semibold tracking-tight">
              {formatNum(r?.pesan_masuk ?? totalPesan)} <span className="text-[14px] font-medium text-muted-foreground">pesan</span>
            </div>
            <div className="mt-1.5 flex items-center gap-2 text-[12.5px] text-muted-foreground">
              <DeltaPill value={kpi?.delta.otomatis_persen ?? null} good={(kpi?.delta.otomatis_persen ?? 0) >= 0} format={formatPct} />
              perubahan porsi dijawab otomatis
            </div>
          </div>
          {kpi ? <VolumeChart data={kpi.harian} /> : <div className="shimmer h-60 rounded-lg" />}
        </Panel>

        <Panel className="flex flex-col p-5">
          <CardHeader icon={<Users />} title="Pesan 7 hari" aside={<Pill>Harian</Pill>} />
          <div className="mt-4">
            <div className="tabular text-[28px] leading-9 font-semibold tracking-tight">{formatNum(week)}</div>
            <div className="mt-1.5 flex items-center gap-2 text-[12.5px] text-muted-foreground">
              <DeltaPill value={weekDelta} good={weekDelta >= 0} />
              dibanding 7 hari sebelumnya
            </div>
          </div>
          <div className="mt-auto pt-4">
            {kpi ? <WeekBars data={last7.map((d) => ({ tanggal: d.tanggal, value: d.pesan }))} /> : <div className="shimmer h-56 rounded-lg" />}
          </div>
        </Panel>
      </motion.div>

      <motion.div variants={item} className="grid gap-4 lg:grid-cols-3">
        <Panel className="p-5">
          <CardHeader icon={<TrendingUp />} title="Funnel lead" aside={<span className="text-[12px] text-subtle-foreground">dari Ledger</span>} />
          <div className="mt-5">{kpi ? <FunnelChart data={kpi.funnel} /> : <SkeletonRows rows={5} />}</div>
        </Panel>

        <Panel className="overflow-hidden lg:col-span-2">
          <div className="p-5 pb-4">
            <CardHeader
              icon={<ClipboardCheck />}
              title="Butuh tindakan"
              aside={
                <Link href="/approval" className="text-[13px] font-semibold text-blue-600 hover:underline">
                  Lihat semua
                </Link>
              }
            />
          </div>
          {!ap ? (
            <SkeletonRows rows={4} className="px-5 pb-5" />
          ) : ap.items.length === 0 ? (
            <EmptyState title="Antrean kosong" description="Semua chat sudah ditangani AI atau staf." className="py-8" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead className="bg-soft text-left text-[11.5px] tracking-[0.04em] text-muted-foreground uppercase">
                  <tr>
                    <th className="px-5 py-2.5 font-medium">Pembeli</th>
                    <th className="px-3 py-2.5 font-medium">Intent</th>
                    <th className="px-3 py-2.5 font-medium">Alasan</th>
                    <th className="px-3 py-2.5 font-medium">Draf</th>
                    <th className="px-5 py-2.5 text-right font-medium">Menunggu</th>
                  </tr>
                </thead>
                <tbody>
                  {ap.items.slice(0, 6).map((a) => (
                    <tr key={a.id} className="border-t border-line hover:bg-blue-50/60">
                      <td className="px-5 py-3">
                        <Link href={`/approval?id=${a.id}`} className="font-medium hover:text-navy-700">
                          {contactName(a.contact)}
                        </Link>
                      </td>
                      <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">{INTENT_LABEL[a.intent ?? ""] ?? a.intent}</td>
                      <td className="max-w-[18rem] px-3 py-3 text-muted-foreground">
                        <span className="line-clamp-1">{a.alasan}</span>
                      </td>
                      <td className="px-3 py-3">{a.verdict ? <VerdictBadge verdict={a.verdict} /> : <span className="text-subtle-foreground">—</span>}</td>
                      <td className="px-5 py-3 text-right whitespace-nowrap text-muted-foreground">{relativeTime(a.dibuat_pada)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </motion.div>
    </motion.div>
  )
}
