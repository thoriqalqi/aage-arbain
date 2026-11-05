"use client"

import { ExternalLink, LoaderCircle, ShieldQuestion } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { api, fetcher } from "@/lib/api"
import { formatDateTime, formatDuration } from "@/lib/format"
import type { AuditStatus, ComplianceAudit, Tinjauan } from "@/lib/types"
import { cn } from "@/lib/utils"

export const kunciTinjauan = (draftId: number) => `/api/compliance/tinjauan/${draftId}`

const STATUS_AUDIT: Record<AuditStatus, { label: string; cls: string }> = {
  BLOCKED: { label: "Diblokir", cls: "bg-blocked-bg text-blocked" },
  NEED_REVIEW: { label: "Perlu tinjauan", cls: "bg-review-bg text-review" },
  ALLOWED: { label: "Tidak ada temuan", cls: "bg-ok-bg text-ok" },
  ERROR: { label: "Audit gagal", cls: "bg-soft text-muted-foreground" },
}

export const STATUS_KEPUTUSAN: Record<string, { label: string; cls: string }> = {
  menunggu: { label: "Menunggu", cls: "bg-escalate-bg text-escalate" },
  disetujui: { label: "Disetujui", cls: "bg-ok-bg text-ok" },
  ditolak: { label: "Ditolak", cls: "bg-blocked-bg text-blocked" },
  revisi: { label: "Diminta revisi", cls: "bg-review-bg text-review" },
}

function Lencana({ label, cls }: { label: string; cls: string }) {
  return <span className={cn("inline-flex h-5 shrink-0 items-center rounded-md px-1.5 text-[11.5px] font-semibold", cls)}>{label}</span>
}

/** Putusan draf memakai audit paling ketat atas teks persis ini, jadi audit itulah yang ditampilkan sebagai alasan. */
function auditPenentu(audits: Tinjauan["audits"]) {
  const berlaku = audits.filter((a) => a.berlaku)
  return berlaku.find((a) => a.status === "BLOCKED") ?? berlaku.find((a) => a.status === "NEED_REVIEW") ?? berlaku[0] ?? null
}

const RISIKO: Record<string, string> = { LOW: "rendah", MEDIUM: "sedang", HIGH: "tinggi", CRITICAL: "kritis" }

function RincianAudit({ audit, kategori }: { audit: ComplianceAudit; kategori: Tinjauan["kategori"] }) {
  const gagal = audit.status === "ERROR"
  return (
    <div className="space-y-3 rounded-lg border border-line bg-white p-3 text-[13px]">
      <div className="flex flex-wrap items-center gap-2">
        <Lencana {...STATUS_AUDIT[audit.status]} />
        <span className="text-[12px] text-subtle-foreground">
          {audit.stage === "aturan" ? "Tahap aturan" : "Tahap LLM"} · {formatDateTime(audit.created_at)} · {formatDuration(audit.duration_ms)}
        </span>
      </div>
      <p>{gagal ? "Audit tidak selesai, jadi putusan draf tidak berubah. Pemeriksaan ini boleh diulang." : audit.reason}</p>
      {audit.evidence.length > 0 && (
        <ul className="space-y-2">
          {audit.evidence.map((e, i) => (
            <li key={i} className="rounded-md bg-soft/70 p-2.5">
              <p className="font-medium break-words">“{e.kutipan}”</p>
              <p className="mt-0.5 text-muted-foreground">{e.alasan}</p>
              <p className="mt-1 text-[11.5px] text-subtle-foreground">
                {e.rule_id ?? "Tanpa aturan"} · {kategori[e.kategori]?.label ?? e.kategori} · risiko {RISIKO[e.risiko] ?? e.risiko}
              </p>
              {kategori[e.kategori]?.celah_bukti && <p className="mt-0.5 text-[12px] text-muted-foreground">Celah bukti: {kategori[e.kategori].celah_bukti}</p>}
            </li>
          ))}
        </ul>
      )}
      {audit.recommendation && (
        <div className="rounded-md bg-ok-bg p-2.5">
          <p className="text-[11px] font-semibold tracking-wide text-ok uppercase">Saran perbaikan, periksa sebelum dipakai</p>
          <p className="mt-0.5 break-words">{audit.recommendation}</p>
          {audit.recommendation_note && <p className="mt-1 text-[12px] text-muted-foreground">{audit.recommendation_note}</p>}
        </div>
      )}
      {audit.violation_law && <p className="text-[12.5px]"><span className="font-medium">Rujukan:</span> {audit.violation_law}</p>}
      {audit.regulatory_note && <p className="text-[12.5px] text-muted-foreground">{audit.regulatory_note}</p>}
      {audit.references.length > 0 && (
        <ul className="space-y-1 text-[12.5px]">
          {audit.references.slice(0, 5).map((r) => (
            <li key={r.ref_id}>
              <a href={r.official_source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-forest-700 hover:underline">
                {r.singkat} · {r.article_reference} <ExternalLink className="size-3" aria-hidden />
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** Temuan audit dan riwayat keputusan satu draf. Membaca tidak memanggil LLM; hanya tombol audit yang memakai kuota. */
export function TinjauanPanel({ draftId, bisaAudit = false, onAudited }: { draftId: number; bisaAudit?: boolean; onAudited?: () => void }) {
  const { data, error, mutate } = useSWR<Tinjauan>(kunciTinjauan(draftId), fetcher)
  const [jalan, setJalan] = useState(false)

  async function audit() {
    if (!data?.product_sku) return
    setJalan(true)
    try {
      const r = await api<{ audit: ComplianceAudit }>("/api/compliance/audit", { method: "POST", json: { product_id: data.product_sku, draft_id: draftId } })
      await mutate()
      onAudited?.()
      if (r.audit.status === "ERROR") toast.error("Audit LLM gagal. Putusan draf tidak berubah.")
      else toast.success(`Audit selesai: ${STATUS_AUDIT[r.audit.status].label}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Audit gagal dijalankan")
    } finally {
      setJalan(false)
    }
  }

  if (error && !data) return <p className="text-[13px] text-muted-foreground">Data tinjauan belum bisa dimuat dari server.</p>
  if (!data) return <div className="shimmer h-24 rounded-lg" />

  const penentu = auditPenentu(data.audits)
  const lainnya = data.audits.filter((a) => a !== penentu)
  const terkunci = data.status === "diarsipkan" || !data.product_sku
  return (
    <div className="space-y-4">
      {bisaAudit && (
        <div className="flex flex-wrap items-center gap-3">
          <AButton variant="outline" onClick={audit} disabled={jalan || terkunci}>
            {jalan ? <LoaderCircle className="size-4 animate-spin" /> : <ShieldQuestion className="size-4" />}
            {jalan ? "Mengaudit…" : "Audit dengan LLM"}
          </AButton>
          <span className="text-[12px] text-subtle-foreground">
            {data.product_sku ? "Memakai kuota LLM dan bisa sampai 1 menit. Audit hanya bisa memperketat putusan." : "Draf ini tidak terhubung ke produk, jadi tidak bisa diaudit."}
          </span>
        </div>
      )}

      {penentu ? (
        <RincianAudit audit={penentu} kategori={data.kategori} />
      ) : (
        <p className="text-[13px] text-muted-foreground">
          {data.audits.length > 0 ? "Teks sudah berubah sejak audit terakhir, jadi temuan lama tidak berlaku lagi." : "Belum ada audit LLM untuk draf ini. Pemeriksaan aturan tetap berjalan otomatis."}
        </p>
      )}

      {data.keputusan.length > 0 && (
        <section>
          <h3 className="mb-1.5 text-[12px] font-medium text-muted-foreground">Riwayat keputusan</h3>
          <ul className="divide-y divide-line rounded-lg border border-line bg-white text-[13px]">
            {data.keputusan.map((k) => {
              const s = STATUS_KEPUTUSAN[k.status] ?? { label: k.status, cls: "bg-soft text-muted-foreground" }
              return (
                <li key={k.approval_id} className="px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Lencana {...s} />
                    <span className="text-[12px] text-subtle-foreground">
                      {k.ditinjau_oleh ? `${k.ditinjau_oleh} · ` : "Diajukan · "}
                      {formatDateTime(k.diputus_pada ?? k.dibuat_pada)}
                    </span>
                  </div>
                  {k.catatan && <p className="mt-1 break-words">{k.catatan}</p>}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {lainnya.length > 0 && (
        <section>
          <h3 className="mb-1.5 text-[12px] font-medium text-muted-foreground">Audit lainnya</h3>
          <ul className="divide-y divide-line rounded-lg border border-line bg-white text-[13px]">
            {lainnya.map((a) => (
              <li key={a.audit_id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                <Lencana {...STATUS_AUDIT[a.status]} />
                <span className="text-[12px] text-subtle-foreground">
                  {a.oleh ? `${a.oleh} · ` : ""}
                  {formatDateTime(a.created_at)}
                  {a.draft_versi ? ` · versi ${a.draft_versi}` : ""}
                  {a.berlaku ? "" : " · teks sudah berubah"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
