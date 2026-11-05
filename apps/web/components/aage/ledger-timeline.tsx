"use client"

import {
  ArrowDownLeft,
  ArrowUpRight,
  Clock,
  ClipboardCheck,
  Compass,
  FileSearch,
  FlaskConical,
  Gavel,
  type LucideIcon,
  PenLine,
  ReceiptText,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRoundCheck,
} from "lucide-react"
import { motion } from "motion/react"

import { formatDuration, formatTime } from "@/lib/format"
import type { LedgerEvent } from "@/lib/types"
import { cn } from "@/lib/utils"

import { SourceChip } from "./source-chip"
import { CostChip, VerdictBadge } from "./status"

export const EVENT_META: Record<string, { label: string; icon: LucideIcon }> = {
  pesan_masuk: { label: "Pesan masuk", icon: ArrowDownLeft },
  intent: { label: "Intent dikenali", icon: Compass },
  retrieval: { label: "Pengambilan sumber", icon: FileSearch },
  draf_jawaban: { label: "Draf jawaban", icon: PenLine },
  gaya_bahasa: { label: "Gaya bahasa (kunci fakta)", icon: PenLine },
  memori_dihapus: { label: "Memori percakapan kedaluwarsa", icon: Clock },
  permintaan_tak_terpenuhi: { label: "Permintaan di luar katalog", icon: Clock },
  claimguard: { label: "ClaimGuard", icon: ShieldCheck },
  claimguard_inbound: { label: "ClaimGuard: klaim diminta", icon: ShieldCheck },
  kebijakan: { label: "Keputusan kebijakan", icon: Gavel },
  approval_dibuat: { label: "Masuk antrean approval", icon: UserRoundCheck },
  approval_diputus: { label: "Approval diputus", icon: ClipboardCheck },
  pesan_keluar: { label: "Pesan keluar", icon: ArrowUpRight },
  draf_pesanan: { label: "Draf pesanan", icon: ReceiptText },
  konten_dibuat: { label: "Konten dibuat", icon: Sparkles },
  konten_disetujui: { label: "Konten disetujui", icon: ClipboardCheck },
  konten_diekspor: { label: "Konten diekspor", icon: ArrowUpRight },
  audit_halaman: { label: "Audit halaman", icon: FileSearch },
  prospek_dibuat: { label: "Prospek dibuat", icon: Compass },
  prospek_status: { label: "Status prospek", icon: Gavel },
  pengingat_repeat_order: { label: "Pengingat repeat order", icon: ArrowUpRight },
  katalog_diimpor: { label: "Katalog diimpor", icon: FileSearch },
  dokumen_diingest: { label: "Dokumen di-ingest", icon: FileSearch },
  claimguard_playground: { label: "Playground ClaimGuard", icon: ShieldCheck },
  prospek_riset: { label: "Riset prospek", icon: FileSearch },
  agen_hitl: { label: "Agen: menunggu manusia", icon: UserRoundCheck },
  agen_claimguard: { label: "Agen ClaimGuard", icon: ShieldCheck },
  invoice_dikirim: { label: "Invoice dikirim", icon: ReceiptText },
  invoice_disusun: { label: "Invoice disusun (tidak dikirim)", icon: ReceiptText },
  klaim_diverifikasi: { label: "Klaim produk diverifikasi", icon: ShieldCheck },
  fakta_status_diubah: { label: "Status verifikasi fakta diubah", icon: ShieldCheck },
  fakta_tertahan: { label: "Fakta belum terverifikasi ditahan", icon: ShieldCheck },
  pengaturan_diubah: { label: "Pengaturan diubah", icon: SlidersHorizontal },
  evaluasi_dimulai: { label: "Evaluasi dimulai", icon: FlaskConical },
  evaluasi_selesai: { label: "Evaluasi selesai", icon: FlaskConical },
}

export function actorLabel(aktor: string) {
  if (aktor === "AI") return "AI"
  if (aktor.startsWith("AI:")) return `AI · ${aktor.slice(3)}`
  if (aktor === "pembeli") return "Pembeli"
  return aktor.replace(/^staf:/, "Staf · ")
}

/** Timeline vertikal event Ledger dengan garis penghubung biru tipis (design.md §7.2). */
export function LedgerTimeline({
  events,
  onSelect,
  highlightId,
  dense = false,
}: {
  events: LedgerEvent[]
  onSelect?: (e: LedgerEvent) => void
  highlightId?: number
  dense?: boolean
}) {
  return (
    <ol className="relative space-y-0">
      {events.map((e, i) => {
        const meta = EVENT_META[e.tipe_event] ?? { label: e.tipe_event, icon: Sparkles }
        const Icon = meta.icon
        const last = i === events.length - 1
        return (
          <motion.li
            key={e.id}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.24, delay: Math.min(i, 12) * 0.04, ease: [0.22, 1, 0.36, 1] }}
            className="relative flex gap-3 pb-4"
          >
            {!last && <span className="absolute top-7 bottom-0 left-[13px] w-px bg-brand-500/30" aria-hidden />}
            <span
              className={cn(
                "relative z-10 mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border bg-white text-forest-700",
                highlightId === e.id ? "ring-once border-brand-500" : "border-line",
              )}
            >
              <Icon className="size-3.5" strokeWidth={1.75} aria-hidden />
            </span>
            <div
              role={onSelect ? "button" : undefined}
              tabIndex={onSelect ? 0 : undefined}
              onClick={onSelect ? () => onSelect(e) : undefined}
              onKeyDown={onSelect ? (ev) => (ev.key === "Enter" || ev.key === " ") && onSelect(e) : undefined}
              className={cn("min-w-0 flex-1 rounded-md text-left", onSelect && "-mx-2 cursor-pointer px-2 py-0.5 hover:bg-soft")}
            >
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="text-[13px] font-semibold">{meta.label}</span>
                <span className="font-mono text-[11px] text-subtle-foreground">{formatTime(e.waktu)}</span>
                <span className="text-[11px] text-muted-foreground">· {actorLabel(e.aktor)}</span>
                {e.verdict && <VerdictBadge verdict={e.verdict} rules={e.aturan_terpicu} />}
                {e.biaya_rp > 0 && <CostChip value={e.biaya_rp} />}
                {e.latensi_ms != null && e.tipe_event === "pesan_keluar" && (
                  <span className="text-[11px] text-subtle-foreground">respons {formatDuration(e.latensi_ms)}</span>
                )}
              </div>
              {!dense && e.ringkasan && <p className="mt-0.5 line-clamp-2 text-[12.5px] text-muted-foreground">{e.ringkasan}</p>}
              {!dense && e.alasan && e.tipe_event !== "pesan_masuk" && (
                <p className="mt-0.5 line-clamp-2 text-[12px] text-subtle-foreground">{e.alasan}</p>
              )}
              {!dense && e.sumber_ref?.some((s) => s.chunk_id) && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {e.sumber_ref.filter((s) => s.chunk_id).slice(0, 3).map((s, j) => <SourceChip key={j} source={s} />)}
                </div>
              )}
            </div>
          </motion.li>
        )
      })}
    </ol>
  )
}
