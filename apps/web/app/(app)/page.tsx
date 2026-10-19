"use client"

import { ArrowRight, Bot, Coins, MessagesSquare, ShieldX } from "lucide-react"
import Link from "next/link"
import { motion } from "motion/react"
import useSWR from "swr"

import { FunnelChart, KpiTile, VolumeChart } from "@/components/aage/charts"
import { EmptyState, SkeletonRows } from "@/components/aage/empty-state"
import { GlassCard, PageHeader, SectionTitle, Surface } from "@/components/aage/glass-card"
import { ConversationStatus, VerdictBadge } from "@/components/aage/status"
import { fetcher } from "@/lib/api"
import { contactName, formatDuration, formatNum, formatPct, formatRp, relativeTime } from "@/lib/format"
import { INTENT_LABEL, type Approval, type Kpi } from "@/lib/types"

const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.04 } } }
const item = { hidden: { opacity: 0, y: 8 }, show: { opacity: 1, y: 0, transition: { duration: 0.24, ease: [0.22, 1, 0.36, 1] as const } } }

export default function RingkasanPage() {
  const { data: kpi } = useSWR<Kpi>("/api/kpi", fetcher, { refreshInterval: 15000 })
  const { data: ap } = useSWR<{ items: Approval[] }>("/api/approvals?status=menunggu", fetcher, { refreshInterval: 8000 })
  const r = kpi?.ringkasan
  const last7 = kpi?.harian.slice(-7) ?? []

  return (
    <motion.div variants={stagger} initial="hidden" animate="show">
      <motion.div variants={item}>
        <PageHeader
          title="Ringkasan"
          description="Kinerja asisten AI 14 hari terakhir — semua angka dihitung langsung dari Evidence-to-Action Ledger."
        />
      </motion.div>

      <motion.div variants={item} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {r ? (
          <>
            <KpiTile label="Chat 14 hari" value={r.chat} delta={kpi?.delta.chat} spark={last7.map((d) => d.chat)}
              hint={`${formatNum(r.pesan_masuk)} pesan`} icon={<MessagesSquare className="size-4 text-emerald-700" />} />
            <KpiTile label="Dijawab otomatis" value={r.otomatis_persen} format={formatPct} delta={kpi?.delta.otomatis_persen}
              deltaFormat={formatPct} spark={last7.map((d) => d.otomatis_persen)} hint={`p95 ${formatDuration(r.respons_ai_p95_ms)}`}
              icon={<Bot className="size-4 text-emerald-700" />} />
            <KpiTile label="Klaim diblokir / ditahan" value={r.klaim_diblokir} delta={kpi?.delta.klaim_diblokir}
              deltaGoodWhenUp={false} spark={last7.map((d) => d.diblokir)} hint={`${r.klaim_ditahan} ditahan`}
              icon={<ShieldX className="size-4 text-blocked" />} />
            <KpiTile label="Biaya AI per percakapan" value={r.biaya_per_percakapan_rp} format={(v) => formatRp(v, { decimals: true })}
              delta={kpi?.delta.biaya_per_percakapan_rp} deltaGoodWhenUp={false} deltaFormat={(v) => formatRp(v, { decimals: true })}
              spark={last7.map((d) => d.biaya_per_percakapan_rp)} hint={`total ${formatRp(r.biaya_total_rp, { decimals: true })}`}
              icon={<Coins className="size-4 text-champagne-600" />} />
          </>
        ) : (
          Array.from({ length: 4 }).map((_, i) => <div key={i} className="shimmer h-36 rounded-xl" />)
        )}
      </motion.div>

      <motion.div variants={item} className="mt-6 grid gap-4 lg:grid-cols-3">
        <GlassCard className="p-5 lg:col-span-2">
          <SectionTitle aside={<span className="text-[12px] text-muted-foreground">sumber: ledger_events</span>}>Funnel lead</SectionTitle>
          {kpi ? <FunnelChart data={kpi.funnel} /> : <SkeletonRows rows={5} />}
        </GlassCard>

        <GlassCard className="flex flex-col p-5">
          <SectionTitle
            aside={
              <Link href="/approval" className="inline-flex items-center gap-1 text-[13px] font-medium text-emerald-700 hover:underline">
                Buka antrean <ArrowRight className="size-3.5" />
              </Link>
            }
          >
            Butuh tindakan
          </SectionTitle>
          {!ap ? (
            <SkeletonRows rows={4} />
          ) : ap.items.length === 0 ? (
            <EmptyState title="Antrean kosong" description="Semua chat sudah ditangani AI atau staf." className="py-6" />
          ) : (
            <ul className="-mx-2 space-y-1">
              {ap.items.slice(0, 5).map((a) => (
                <li key={a.id}>
                  <Link href={`/approval?id=${a.id}`} className="flex items-start gap-3 rounded-md px-2 py-2 hover:bg-white/60">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate font-medium">{contactName(a.contact)}</span>
                        <span className="ml-auto shrink-0 text-[11px] text-subtle-foreground">{relativeTime(a.dibuat_pada)}</span>
                      </div>
                      <p className="line-clamp-1 text-[12.5px] text-muted-foreground">{a.alasan}</p>
                      <div className="mt-1 flex gap-1.5">
                        <ConversationStatus status={a.objek_tipe === "order_draft" ? "otomatis" : "eskalasi"} compact />
                        <span className="text-[12px] text-subtle-foreground">· {INTENT_LABEL[a.intent ?? ""] ?? a.intent}</span>
                        {a.verdict && <VerdictBadge verdict={a.verdict} className="ml-auto" />}
                      </div>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </GlassCard>
      </motion.div>

      <motion.div variants={item} className="mt-6">
        <Surface className="p-5">
          <SectionTitle aside={<span className="text-[12px] text-muted-foreground">otomatis vs eskalasi per hari</span>}>Volume chat 14 hari</SectionTitle>
          {kpi ? <VolumeChart data={kpi.harian} /> : <div className="shimmer h-64 rounded-md" />}
        </Surface>
      </motion.div>
    </motion.div>
  )
}
