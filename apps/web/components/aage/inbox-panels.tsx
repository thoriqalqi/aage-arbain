"use client"

import { Check, Clock, Pencil, Sparkles, TriangleAlert, X } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { AButton } from "@/components/aage/button"
import { VerdictBadge } from "@/components/aage/status"
import { ApiError, api } from "@/lib/api"
import { formatTime, formatWait, minutesSince } from "@/lib/format"
import type { Approval, CheckResult, Contact, ConversationDetail } from "@/lib/types"
import { cn } from "@/lib/utils"

const SLA_MENIT = 15

/** Lama pembeli menunggu staf. Merah setelah melewati SLA 15 menit. */
export function WaitBadge({ since, className }: { since: string | null | undefined; className?: string }) {
  const min = minutesSince(since)
  if (min == null) return null
  const late = min >= SLA_MENIT
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-full px-1.5 text-[11px] font-semibold tabular-nums",
        late ? "bg-blocked-bg text-blocked" : "bg-escalate-bg text-escalate",
        className,
      )}
      title={`Menunggu staf sejak ${formatTime(since)}`}
    >
      <Clock className="size-3" aria-hidden /> {formatWait(min)}
    </span>
  )
}

export function WindowNotice({ jendela }: { jendela: ConversationDetail["jendela"] }) {
  if (!jendela.berlaku || jendela.terbuka) return null
  return (
    <div className="mx-3 mb-2 flex gap-2 rounded-lg bg-review-bg p-3 text-[13px] text-review">
      <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>
        Sudah lewat {jendela.jam ?? 24} jam sejak pesan terakhir pembeli. WhatsApp akan <b>menolak teks bebas</b>; kirim template yang sudah
        disetujui (mis. pengingat repeat order) atau tunggu pembeli membalas lebih dulu.
      </span>
    </div>
  )
}

export function SaranAI({ saran, onUse }: { saran: ConversationDetail["saran_ai"]; onUse: (t: string) => void }) {
  if (!saran) return null
  return (
    <div className="mx-3 mb-2 rounded-lg border border-line bg-white p-3 text-[13px]">
      <div className="mb-1 flex items-center gap-2 font-medium text-forest-700">
        <Sparkles className="size-4" aria-hidden /> Saran AI untuk pesan terakhir
        {saran.verdict && <VerdictBadge verdict={saran.verdict} />}
      </div>
      {saran.teks ? (
        <>
          <p className="line-clamp-4 whitespace-pre-line text-muted-foreground">{saran.teks}</p>
          <AButton size="sm" variant="glass" className="mt-2" onClick={() => onUse(saran.teks!)}>
            Pakai saran ini
          </AButton>
        </>
      ) : (
        <p className="text-muted-foreground">Tidak ada saran yang lolos ClaimGuard{saran.catatan ? ` — ${saran.catatan}` : ""}. Balas manual.</p>
      )}
    </div>
  )
}

/** Approval percakapan ini bisa diputus langsung dari chat, tanpa pindah ke halaman Approval. */
export function InlineApprovals({ approvals, onDone }: { approvals: Approval[]; onDone: () => void }) {
  const pending = approvals.filter((a) => a.status === "menunggu" && a.objek_tipe !== "konten")
  const [editing, setEditing] = useState<number | null>(null)
  const [text, setText] = useState("")
  const [busy, setBusy] = useState(false)
  const [blocked, setBlocked] = useState<CheckResult | null>(null)
  if (!pending.length) return null

  async function decide(a: Approval, aksi: "setujui" | "edit" | "tolak", teks?: string) {
    setBusy(true)
    setBlocked(null)
    try {
      await api(`/api/approvals/${a.id}/decide`, { method: "POST", json: { aksi, teks } })
      setEditing(null)
      toast.success(aksi === "tolak" ? "Draf ditolak — tidak ada pesan terkirim." : "Terkirim ke pembeli")
      onDone()
    } catch (err) {
      if (err instanceof ApiError) {
        const cg = (err.detail as { claimguard?: CheckResult })?.claimguard
        if (cg) setBlocked(cg)
        toast.error(err.message)
      } else toast.error("Gagal memproses approval")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-3 mb-2 space-y-2">
      {pending.map((a) => (
        <div key={a.id} className="rounded-lg bg-escalate-bg/70 p-3 text-[13px]">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <div className="font-semibold text-escalate">
                {a.objek_tipe === "order_draft" ? "Konfirmasi draf pesanan" : "Menunggu keputusan staf"}
              </div>
              <div className="text-muted-foreground">{a.alasan}</div>
            </div>
            <WaitBadge since={a.dibuat_pada} />
          </div>
          {editing === a.id ? (
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              className="mt-2 w-full rounded-md border border-line bg-white p-2 text-[13px] outline-none"
              aria-label="Edit draf balasan"
            />
          ) : a.draf ? (
            <p className="mt-2 line-clamp-5 whitespace-pre-line rounded-md bg-white/80 p-2">{a.draf}</p>
          ) : (
            <p className="mt-2 text-muted-foreground italic">Belum ada draf — tulis balasan staf.</p>
          )}
          {blocked && editing === a.id && blocked.safe_text && (
            <button className="mt-1 text-left text-blocked underline" onClick={() => setText(blocked.safe_text)}>
              ClaimGuard menolak — pakai versi aman
            </button>
          )}
          <div className="mt-2 flex flex-wrap gap-2">
            {editing === a.id ? (
              <>
                <AButton size="sm" disabled={busy || !text.trim()} onClick={() => decide(a, "edit", text)}>
                  <Check className="size-3.5" /> Kirim hasil edit
                </AButton>
                <AButton size="sm" variant="ghost" onClick={() => setEditing(null)}>Batal</AButton>
              </>
            ) : (
              <>
                {a.draf && (
                  <AButton size="sm" disabled={busy} onClick={() => decide(a, "setujui")}>
                    <Check className="size-3.5" /> Setujui & kirim
                  </AButton>
                )}
                <AButton size="sm" variant="glass" disabled={busy} onClick={() => { setEditing(a.id); setText(a.draf ?? "") }}>
                  <Pencil className="size-3.5" /> {a.draf ? "Edit" : "Tulis balasan"}
                </AButton>
                <AButton size="sm" variant="destructive" disabled={busy} onClick={() => decide(a, "tolak")}>
                  <X className="size-3.5" /> Tolak
                </AButton>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

export function ContactEditor({ contact, onSaved }: { contact: Contact; onSaved: () => void }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ nama_toko: "", tipe_toko: "", alamat: "", telepon: "" })
  const [busy, setBusy] = useState(false)

  if (!open) {
    return (
      <button
        className="text-[12px] font-medium text-forest-700 hover:underline"
        onClick={() => {
          setForm({ nama_toko: contact.nama_toko ?? "", tipe_toko: contact.tipe_toko ?? "", alamat: contact.alamat ?? "", telepon: "" })
          setOpen(true)
        }}
      >
        Edit profil toko
      </button>
    )
  }

  async function save() {
    setBusy(true)
    try {
      // Nomor HP hanya dikirim bila diisi (nomor lama ditampilkan termasking dan tidak ditimpa tanpa sengaja).
      await api(`/api/contacts/${contact.id}`, { method: "PATCH", json: { ...form, telepon: form.telepon || undefined } })
      toast.success(form.telepon ? "Profil disimpan, nomor HP ditautkan ke riwayat pesanan" : "Profil toko disimpan")
      setOpen(false)
      onSaved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Gagal menyimpan profil")
    } finally {
      setBusy(false)
    }
  }

  const field = (key: keyof typeof form, label: string) => (
    <label className="block text-[12px] text-muted-foreground">
      {label}
      <input
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        className="mt-0.5 h-8 w-full rounded-md border border-line bg-white px-2 text-[13px] text-foreground outline-none"
      />
    </label>
  )
  return (
    <div className="space-y-2 rounded-lg border border-line p-3">
      {field("nama_toko", "Nama toko")}
      {field("tipe_toko", "Jenis toko (apotek, toko obat, …)")}
      {field("alamat", "Alamat pengiriman")}
      {field("telepon", contact.wa_number ? `Nomor HP (saat ini ${contact.wa_number}) — isi untuk mengganti` : "Nomor HP — tautkan ke riwayat pesanan pembeli lama")}
      <div className="flex gap-2">
        <AButton size="sm" disabled={busy} onClick={save}>Simpan</AButton>
        <AButton size="sm" variant="ghost" onClick={() => setOpen(false)}>Batal</AButton>
      </div>
    </div>
  )
}
