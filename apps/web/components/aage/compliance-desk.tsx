"use client"

import {
  BadgeCheck,
  ExternalLink,
  FileWarning,
  Loader2,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Sparkles,
  Trash2,
  TriangleAlert,
  WifiOff,
} from "lucide-react"
import { useState } from "react"

import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { formatDateTime, formatDuration, relativeTime } from "@/lib/format"
import type { AuditStatus, ComplianceAudit, ComplianceEvidence, MarketingDraft, RegulatoryReference } from "@/lib/types"
import { cn } from "@/lib/utils"

export const DRAFT_STATUS: Record<MarketingDraft["status"], { label: string; cls: string }> = {
  draf: { label: "Draf", cls: "bg-soft text-muted-foreground" },
  diblokir: { label: "Diblokir", cls: "bg-blocked-bg text-blocked" },
  perlu_review: { label: "Perlu review", cls: "bg-review-bg text-review" },
  lolos_pemeriksaan: { label: "Lolos pemeriksaan", cls: "bg-ok-bg text-ok" },
  audit_gagal: { label: "Audit gagal", cls: "bg-zinc-100 text-zinc-700" },
  menunggu_audit_ulang: { label: "Menunggu audit ulang", cls: "bg-info-bg text-info" },
  disetujui: { label: "Disetujui manusia", cls: "bg-forest-900 text-white" },
  dibuang: { label: "Dibuang", cls: "bg-zinc-100 text-zinc-500 line-through" },
}

const btnBase =
  "inline-flex h-9 items-center justify-center gap-2 rounded-[10px] px-3.5 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-45"
const btnGreen = cn(btnBase, "bg-emerald-600 text-white hover:bg-emerald-500 focus-visible:outline-emerald-400")
const btnNeutral = cn(btnBase, "border border-zinc-700 bg-zinc-800/80 text-zinc-100 hover:bg-zinc-700 focus-visible:outline-zinc-400")

export type DeskActions = {
  onApply: (audit: ComplianceAudit) => Promise<void>
  onDiscard: (alasan: string) => Promise<void>
  onApprove: (catatan: string) => Promise<void>
  onReaudit: () => Promise<void>
}

/** Sorot teks draf sesuai offset bukti audit (hanya bukti dengan posisi yang valid). */
export function EvidenceText({ text, evidence, tone }: { text: string; evidence: ComplianceEvidence[]; tone: AuditStatus }) {
  const spans = evidence
    .filter((e): e is ComplianceEvidence & { start: number; end: number } => e.start != null && e.end != null && e.end <= text.length)
    .sort((a, b) => a.start - b.start)
  const nodes: React.ReactNode[] = []
  let cursor = 0
  spans.forEach((e, i) => {
    if (e.start < cursor) return
    if (e.start > cursor) nodes.push(<span key={`t${i}`}>{text.slice(cursor, e.start)}</span>)
    nodes.push(
      <mark
        key={`m${i}`}
        title={`${e.rule_id ?? "LLM"} · ${e.alasan}`}
        className={cn(
          "rounded-sm px-0.5 text-inherit",
          tone === "BLOCKED" ? "bg-red-500/30 underline decoration-red-400 decoration-2" : "bg-amber-400/25 underline decoration-amber-300",
        )}
      >
        {text.slice(e.start, e.end)}
      </mark>,
    )
    cursor = e.end
  })
  if (cursor < text.length) nodes.push(<span key="tail">{text.slice(cursor)}</span>)
  return <p className="text-[13px] leading-6 whitespace-pre-wrap">{nodes}</p>
}

function References({ refs, law, note }: { refs: RegulatoryReference[]; law: string | null; note: string | null }) {
  return (
    <div className="space-y-2">
      <p className="text-[11px] font-semibold tracking-wide uppercase opacity-80">Rujukan regulasi terkait</p>
      {law ? (
        <p className="text-[13px] leading-5 font-medium">{law}</p>
      ) : (
        <p className="inline-flex items-center gap-1.5 rounded-md bg-amber-400/15 px-2 py-1 text-[12.5px] text-amber-200">
          <FileWarning className="size-3.5" aria-hidden /> Rujukan regulasi perlu diverifikasi
        </p>
      )}
      {note && law && <p className="text-[12px] text-amber-200/90">{note}</p>}
      {refs.length > 0 && (
        <ul className="space-y-1.5">
          {refs.map((r) => (
            <li key={r.ref_id} className="rounded-lg bg-black/25 px-3 py-2 text-[12px] leading-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">
                  {r.singkat} · {r.article_reference}
                </span>
                <a
                  href={r.official_source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[11.5px] underline-offset-2 opacity-80 hover:underline hover:opacity-100"
                >
                  peraturan.go.id <ExternalLink className="size-3" aria-hidden />
                </a>
              </div>
              <p className="opacity-75">{r.ringkasan}</p>
              <p className="text-[11px] opacity-60">
                {r.verification_status === "VERIFIED" ? `Terverifikasi dari sumber resmi ${r.last_verified_at}` : "Belum diverifikasi"}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Findings({ audit }: { audit: ComplianceAudit }) {
  if (audit.evidence.length === 0) return null
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-semibold tracking-wide uppercase opacity-80">Bukti ({audit.evidence.length})</p>
      <ul className="space-y-1">
        {audit.evidence.slice(0, 8).map((e, i) => (
          <li key={i} className="flex gap-2 text-[12.5px] leading-5">
            <span className="mt-0.5 shrink-0 rounded bg-black/30 px-1.5 font-mono text-[10.5px]">{e.rule_id ?? "LLM"}</span>
            <span>
              <span className="font-medium">“{e.kutipan.length > 110 ? `${e.kutipan.slice(0, 110)}…` : e.kutipan}”</span>
              <span className="opacity-75"> — {e.alasan}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Meta({ audit }: { audit: ComplianceAudit }) {
  return (
    <p className="text-[11px] leading-5 text-zinc-400">
      Audit {audit.audit_id.slice(0, 8)} · {formatDateTime(audit.created_at)} ({relativeTime(audit.created_at)}) · tahap{" "}
      {audit.stage === "aturan" ? "aturan" : "analisis konteks LLM"}
      {audit.model_name ? ` · ${audit.model_provider}/${audit.model_name}` : ""} · aturan v{audit.rules_version} ·{" "}
      {audit.engine_version} · {formatDuration(audit.duration_ms)}
    </p>
  )
}

export function InterventionDesk({
  audit,
  draft,
  isAdmin,
  busy,
  actions,
}: {
  audit: ComplianceAudit
  draft: MarketingDraft
  isAdmin: boolean
  busy: boolean
  actions: DeskActions
}) {
  const [dialog, setDialog] = useState<null | "apply" | "discard" | "approve">(null)
  const [ack, setAck] = useState(false)
  const [note, setNote] = useState("")
  const stale = audit.draft_versi !== draft.versi
  const closed = draft.status === "dibuang" || draft.status === "disetujui"
  const canAct = !busy && !stale && !closed

  function open(kind: "apply" | "discard" | "approve") {
    setAck(false)
    setNote("")
    setDialog(kind)
  }

  async function run(fn: () => Promise<void>) {
    try {
      await fn()
      setDialog(null)
    } catch {
      /* galat sudah ditampilkan lewat toast; dialog tetap terbuka */
    }
  }

  const recommendationBlock = audit.recommendation ? (
    <div className="rounded-xl border border-emerald-500/30 bg-emerald-950/40 p-3.5 text-emerald-50">
      <p className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-emerald-300 uppercase">
        <Sparkles className="size-3.5" aria-hidden /> Rekomendasi aman (belum diterapkan)
      </p>
      <p className="text-[13px] leading-6">{audit.recommendation}</p>
      {audit.recommendation_note && <p className="mt-1.5 text-[11.5px] text-emerald-200/75">{audit.recommendation_note}</p>}
    </div>
  ) : audit.recommendation_note ? (
    <p className="rounded-lg bg-black/25 px-3 py-2 text-[12px] opacity-80">{audit.recommendation_note}</p>
  ) : null

  const discardBtn = (
    <button type="button" className={btnNeutral} disabled={!canAct} onClick={() => open("discard")}>
      <Trash2 className="size-4" aria-hidden /> Buang Draf
    </button>
  )
  const applyBtn = (
    <button
      type="button"
      className={btnGreen}
      disabled={!canAct || !audit.recommendation}
      title={audit.recommendation ? undefined : "Audit ini tidak punya rekomendasi otomatis — revisi manual"}
      onClick={() => open("apply")}
    >
      <Sparkles className="size-4" aria-hidden /> Terapkan Rekomendasi Aman AI
    </button>
  )

  let card: React.ReactNode
  if (audit.status === "BLOCKED") {
    card = (
      <div
        role="alert"
        className="relative space-y-4 rounded-2xl border-2 border-red-500 bg-red-950/40 p-5 text-red-200 shadow-[0_0_15px_rgba(239,68,68,0.3)] transition-all duration-300"
      >
        {/* Denyut hanya pada bingkai agar teks tetap mudah dibaca; dimatikan bila pengguna memilih reduced motion. */}
        <span aria-hidden className="pointer-events-none absolute inset-0 animate-pulse rounded-2xl ring-4 ring-red-500/40 motion-reduce:animate-none" />
        <div className="flex items-start gap-3">
          <ShieldAlert className="mt-0.5 size-6 shrink-0 text-red-400" aria-hidden />
          <div className="min-w-0">
            <h3 className="font-mono text-[13.5px] font-bold tracking-wide text-red-100">[BPOM COMPLIANCE ALERT: OVERCLAIM DETECTED]</h3>
            <p className="mt-1 text-[13px] leading-5">{audit.reason}</p>
          </div>
        </div>
        <References refs={audit.references} law={audit.violation_law} note={audit.regulatory_note} />
        <Findings audit={audit} />
        {recommendationBlock}
        <div className="relative flex flex-wrap gap-2">
          {applyBtn}
          {discardBtn}
        </div>
      </div>
    )
  } else if (audit.status === "NEED_REVIEW") {
    card = (
      <div role="status" className="space-y-4 rounded-2xl border border-amber-500/60 bg-amber-950/35 p-5 text-amber-100">
        <div className="flex items-start gap-3">
          <ShieldQuestion className="mt-0.5 size-6 shrink-0 text-amber-400" aria-hidden />
          <div className="min-w-0">
            <h3 className="text-[14px] font-semibold text-amber-50">Perlu peninjauan manusia</h3>
            <p className="mt-1 text-[13px] leading-5">{audit.reason}</p>
          </div>
        </div>
        <References refs={audit.references} law={audit.violation_law} note={audit.regulatory_note} />
        <Findings audit={audit} />
        {recommendationBlock}
        <div className="flex flex-wrap gap-2">
          {audit.recommendation && applyBtn}
          <button
            type="button"
            className={btnNeutral}
            disabled={!canAct || !isAdmin}
            title={isAdmin ? undefined : "Hanya admin yang dapat menyetujui draf NEED_REVIEW"}
            onClick={() => open("approve")}
          >
            <BadgeCheck className="size-4" aria-hidden /> Setujui setelah ditinjau
          </button>
          {discardBtn}
        </div>
        {!isAdmin && <p className="text-[11.5px] text-amber-200/70">Persetujuan draf NEED_REVIEW hanya untuk admin, dengan catatan peninjauan.</p>}
      </div>
    )
  } else if (audit.status === "ALLOWED") {
    card = (
      <div role="status" className="space-y-4 rounded-2xl border border-zinc-800 bg-zinc-900/50 p-5 text-zinc-200">
        <div className="flex items-start gap-3">
          <ShieldCheck className="mt-0.5 size-6 shrink-0 text-emerald-400" aria-hidden />
          <div className="min-w-0">
            <h3 className="text-[14px] font-semibold text-emerald-300">Tidak ditemukan pelanggaran oleh pemeriksaan ini</h3>
            <p className="mt-1 text-[13px] leading-5 text-zinc-300">{audit.reason}</p>
            <p className="mt-1 text-[12px] text-zinc-400">Bukan jaminan kepatuhan BPOM — publikasi tetap menunggu persetujuan manusia.</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={btnGreen} disabled={!canAct} onClick={() => open("approve")}>
            <BadgeCheck className="size-4" aria-hidden /> Setujui draf
          </button>
          {discardBtn}
        </div>
      </div>
    )
  } else {
    card = (
      <div role="alert" className="space-y-4 rounded-2xl border border-red-400/30 bg-zinc-900/70 p-5 text-zinc-200">
        <div className="flex items-start gap-3">
          <TriangleAlert className="mt-0.5 size-6 shrink-0 text-red-300" aria-hidden />
          <div className="min-w-0">
            <h3 className="text-[14px] font-semibold text-red-200">Audit gagal — status kepatuhan belum dapat dipastikan</h3>
            <p className="mt-1 text-[13px] leading-5 text-zinc-300">{audit.reason}</p>
            {audit.error_code && <p className="mt-1 font-mono text-[11px] text-zinc-500">kode: {audit.error_code}</p>}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={btnNeutral} disabled={!canAct} onClick={() => actions.onReaudit()}>
            <RefreshCw className="size-4" aria-hidden /> Audit ulang
          </button>
          {discardBtn}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {closed && (
        <p className={cn("rounded-lg px-3 py-2 text-[12.5px]", draft.status === "disetujui" ? "bg-emerald-950/60 text-emerald-200" : "bg-zinc-800 text-zinc-300")}>
          Draf {draft.status === "disetujui" ? "sudah disetujui manusia" : "sudah dibuang"}
          {draft.keputusan_pada ? ` pada ${formatDateTime(draft.keputusan_pada)}` : ""}
          {draft.catatan_keputusan ? ` — “${draft.catatan_keputusan}”` : ""}. Tindakan dinonaktifkan.
        </p>
      )}
      {stale && !closed && (
        <p className="rounded-lg bg-zinc-800 px-3 py-2 text-[12.5px] text-zinc-300">
          Teks draf sudah berubah (versi {draft.versi}) sejak audit ini (versi {audit.draft_versi}). Audit ulang sebelum mengambil tindakan.
        </p>
      )}
      {card}
      <Meta audit={audit} />

      <Dialog open={dialog === "apply"} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>Tinjau rekomendasi aman</DialogTitle>
            <DialogDescription>
              Teks draf #{draft.id} akan diganti dengan rekomendasi lalu diaudit ulang otomatis. Audit lama tetap tersimpan sebagai riwayat.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-line bg-blocked-bg/50 p-3">
              <p className="mb-1 text-[11px] font-semibold tracking-wide text-blocked uppercase">Teks saat ini (v{draft.versi})</p>
              <p className="text-[13px] leading-6 whitespace-pre-wrap">{draft.teks}</p>
            </div>
            <div className="rounded-lg border border-line bg-ok-bg/60 p-3">
              <p className="mb-1 text-[11px] font-semibold tracking-wide text-ok uppercase">Rekomendasi (v{draft.versi + 1})</p>
              <p className="text-[13px] leading-6 whitespace-pre-wrap">{audit.recommendation}</p>
            </div>
          </div>
          {audit.recommendation_note && <p className="text-[12px] text-muted-foreground">{audit.recommendation_note}</p>}
          <label className="flex items-start gap-2 text-[13px]">
            <input type="checkbox" className="mt-1 size-4 accent-emerald-600" checked={ack} onChange={(e) => setAck(e.target.checked)} />
            Saya sudah membaca rekomendasi ini dan menyetujui penyimpanannya ke draf. Saya memahami teks tetap harus ditinjau sebelum dipublikasikan.
          </label>
          <DialogFooter>
            <button type="button" className={cn(btnBase, "btn-glass")} onClick={() => setDialog(null)}>
              Batal
            </button>
            <button type="button" className={btnGreen} disabled={!ack || busy} onClick={() => run(() => actions.onApply(audit))}>
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Sparkles className="size-4" aria-hidden />} Simpan & audit ulang
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={dialog === "discard"} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Buang draf #{draft.id}?</DialogTitle>
            <DialogDescription>
              Draf ditandai “dibuang” dan tidak bisa diaudit atau disetujui lagi. Teks dan riwayat audit tetap disimpan untuk jejak Ledger (tidak dihapus permanen).
            </DialogDescription>
          </DialogHeader>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            maxLength={2000}
            placeholder="Alasan (opsional)"
            aria-label="Alasan membuang draf"
            className="w-full rounded-lg border border-line bg-white p-2.5 text-[13px] outline-none focus:border-brand-500"
          />
          <DialogFooter>
            <button type="button" className={cn(btnBase, "btn-glass")} onClick={() => setDialog(null)}>
              Batal
            </button>
            <button type="button" className={cn(btnBase, "bg-zinc-900 text-white hover:bg-zinc-800")} disabled={busy} onClick={() => run(() => actions.onDiscard(note))}>
              <Trash2 className="size-4" aria-hidden /> Ya, buang draf
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={dialog === "approve"} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Setujui draf #{draft.id}?</DialogTitle>
            <DialogDescription>
              {audit.status === "NEED_REVIEW"
                ? "Audit menandai draf ini perlu review. Tulis hasil peninjauan Anda (min. 10 karakter); keputusan tercatat atas nama Anda di Ledger."
                : "Keputusan persetujuan tercatat atas nama Anda di Ledger. ClaimGuard bukan pengganti tinjauan regulasi."}
            </DialogDescription>
          </DialogHeader>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            maxLength={2000}
            placeholder={audit.status === "NEED_REVIEW" ? "Catatan peninjauan (wajib)" : "Catatan (opsional)"}
            aria-label="Catatan persetujuan"
            className="w-full rounded-lg border border-line bg-white p-2.5 text-[13px] outline-none focus:border-brand-500"
          />
          <DialogFooter>
            <button type="button" className={cn(btnBase, "btn-glass")} onClick={() => setDialog(null)}>
              Batal
            </button>
            <button
              type="button"
              className={btnGreen}
              disabled={busy || (audit.status === "NEED_REVIEW" && note.trim().length < 10)}
              onClick={() => run(() => actions.onApprove(note))}
            >
              <BadgeCheck className="size-4" aria-hidden /> Setujui
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export function DeskConnectionError({ message }: { message: string }) {
  return (
    <p className="flex items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-2 text-[12.5px] text-zinc-300">
      <WifiOff className="size-4 shrink-0 text-zinc-400" aria-hidden /> {message}. Menampilkan status terakhir yang berhasil dimuat; mencoba lagi otomatis.
    </p>
  )
}
