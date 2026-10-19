"use client"

import { Check, Keyboard, MessageSquareText, Pencil, ReceiptText, X } from "lucide-react"
import Link from "next/link"
import { AnimatePresence, motion } from "motion/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { WaText } from "@/components/aage/chat-bubble"
import { EmptyState, SkeletonRows } from "@/components/aage/empty-state"
import { Panel, PageHeader } from "@/components/aage/panel"
import { Pill, VerdictBadge } from "@/components/aage/status"
import { ApiError, api, fetcher } from "@/lib/api"
import { contactName, relativeTime } from "@/lib/format"
import { INTENT_LABEL, type Approval, type CheckResult } from "@/lib/types"
import { cn } from "@/lib/utils"

const AGENT_LABEL: Record<string, string> = {
  agen_negosiasi: "Eskalasi negosiasi · Sales Agent",
  agen_deal_final: "Deal final · Sales Agent",
  agen_konten: "Konten GEO · GEO Agent",
}

function ApprovalCard({
  a,
  focused,
  editing,
  onFocus,
  onEdit,
  onDecide,
  busy,
  error,
}: {
  a: Approval
  focused: boolean
  editing: boolean
  onFocus: () => void
  onEdit: (v: boolean) => void
  onDecide: (aksi: "setujui" | "edit" | "tolak", teks?: string) => void
  busy: boolean
  error: CheckResult | null
}) {
  const [draft, setDraft] = useState(a.draf)
  const ref = useRef<HTMLDivElement>(null)
  const area = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [focused])
  useEffect(() => {
    if (editing) area.current?.focus()
  }, [editing])
  const [head, ...lines] = a.ringkasan.split("\n")
  const isOrder = a.objek_tipe === "order_draft"
  return (
    <motion.div
      layout
      ref={ref}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, x: 120, height: 0, marginBottom: 0, transition: { duration: 0.32, ease: [0.22, 1, 0.36, 1] } }}
      onClick={onFocus}
      className="mb-4"
    >
      <Panel className={cn("p-5 transition-shadow", focused && "shadow-glow ring-1 ring-blue-500/40")}>
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">{contactName(a.contact)}</span>
              <Pill>
                {isOrder ? <ReceiptText className="size-3.5" /> : <MessageSquareText className="size-3.5" />}
                {AGENT_LABEL[a.objek_tipe] ?? (isOrder ? `Draf pesanan #${a.objek_id}` : "Balasan chat")}
              </Pill>
              {a.intent && <Pill>{INTENT_LABEL[a.intent] ?? a.intent}</Pill>}
              <span className="text-[12px] text-subtle-foreground">menunggu {relativeTime(a.dibuat_pada).replace(" lalu", "")}</span>
            </div>
            <p className="mt-1.5 text-[13px] text-escalate">
              <span className="font-semibold">Alasan:</span> {a.alasan}
            </p>
          </div>
          {a.conversation_id && (
            <Link href={`/inbox?id=${a.conversation_id}`} className="text-[13px] font-medium text-navy-700 hover:underline">
              Buka chat
            </Link>
          )}
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg bg-soft/80 p-3 text-[13px]">
            <div className="mb-1.5 text-[12px] font-medium text-muted-foreground">{head}</div>
            <div className="space-y-1">
              {lines.map((l, i) => (
                <p key={i} className="line-clamp-3 text-muted-foreground">
                  <span className="font-medium text-foreground">{l.split(":")[0]}:</span>
                  {l.slice(l.indexOf(":") + 1)}
                </p>
              ))}
            </div>
          </div>
          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <span className="text-[12px] font-medium text-muted-foreground">Draf balasan untuk pembeli</span>
              <VerdictBadge verdict={a.verdict} />
            </div>
            {editing ? (
              <textarea
                ref={area}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={6}
                className="w-full rounded-lg border border-line bg-white p-3 text-[14px] leading-6 outline-none focus:border-blue-500"
                aria-label="Edit draf balasan"
                onKeyDown={(e) => {
                  if (e.key === "Escape") onEdit(false)
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onDecide("edit", draft)
                }}
              />
            ) : (
              <div className="rounded-lg border border-line bg-white p-3 leading-6 whitespace-pre-wrap">
                {a.draf ? <WaText text={a.draf} /> : <span className="text-subtle-foreground">Belum ada draf — tulis balasan lewat Edit.</span>}
              </div>
            )}
            {error && (
              <div className="mt-2 rounded-md bg-blocked-bg p-2.5 text-[13px] text-blocked">
                <div className="flex items-center gap-2 font-semibold">
                  <VerdictBadge verdict={error.verdict} rules={error.rules_triggered} animate /> ClaimGuard menahan teks ini
                </div>
                <button className="mt-1 text-left underline" onClick={() => setDraft(error.safe_text)}>
                  Ganti dengan versi aman
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {editing ? (
            <>
              <AButton onClick={() => onDecide("edit", draft)} disabled={busy || !draft.trim()}>
                <Check className="size-4" /> Simpan & kirim
              </AButton>
              <AButton variant="ghost" onClick={() => onEdit(false)}>
                Batal
              </AButton>
            </>
          ) : (
            <>
              <AButton onClick={() => onDecide("setujui")} disabled={busy || !a.draf}>
                <Check className="size-4" /> Setujui &amp; kirim <kbd className="ml-1 font-mono text-[11px] opacity-60">A</kbd>
              </AButton>
              <AButton variant="outline" onClick={() => onEdit(true)} disabled={busy}>
                <Pencil className="size-4" /> Edit <kbd className="ml-1 font-mono text-[11px] opacity-60">E</kbd>
              </AButton>
              <AButton variant="destructive" onClick={() => onDecide("tolak")} disabled={busy}>
                <X className="size-4" /> Tolak <kbd className="ml-1 font-mono text-[11px] opacity-60">R</kbd>
              </AButton>
            </>
          )}
        </div>
      </Panel>
    </motion.div>
  )
}

export default function ApprovalPage() {
  const { data, mutate } = useSWR<{ items: Approval[] }>("/api/approvals?status=menunggu", fetcher, { refreshInterval: 6000 })
  const items = useMemo(() => data?.items ?? [], [data])
  const [focus, setFocus] = useState(0)
  const [editing, setEditing] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<Record<number, CheckResult>>({})
  const { data: history } = useSWR<{ items: Approval[] }>("/api/approvals?status=semua", fetcher, { refreshInterval: 15000 })

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id")
    if (id && items.length) {
      const idx = items.findIndex((a) => a.id === Number(id))
      if (idx >= 0) setFocus(idx)
    }
  }, [items.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const decide = useCallback(
    async (a: Approval, aksi: "setujui" | "edit" | "tolak", teks?: string) => {
      setBusy(true)
      try {
        await api(`/api/approvals/${a.id}/decide`, { method: "POST", json: { aksi, teks } })
        setEditing(null)
        await mutate({ items: items.filter((x) => x.id !== a.id) }, { revalidate: true })
        if (aksi === "tolak") toast("Draf ditolak — tidak ada pesan terkirim.")
        else toast.success(a.objek_tipe === "order_draft" ? "Pesanan dikonfirmasi & terkirim ke WhatsApp" : "Terkirim ke WhatsApp")
      } catch (err) {
        if (err instanceof ApiError && (err.detail as { claimguard?: CheckResult })?.claimguard) {
          setErrors((e) => ({ ...e, [a.id]: (err.detail as { claimguard: CheckResult }).claimguard }))
          setEditing(a.id)
        }
        toast.error(err instanceof Error ? err.message : "Gagal memproses")
      } finally {
        setBusy(false)
      }
    },
    [items, mutate],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || e.metaKey || e.ctrlKey || busy) return
      const a = items[focus]
      const k = e.key.toLowerCase()
      if (k === "j") setFocus((f) => Math.min(items.length - 1, f + 1))
      else if (k === "k") setFocus((f) => Math.max(0, f - 1))
      else if (!a) return
      else if (k === "a" && a.draf) decide(a, "setujui")
      else if (k === "e") {
        e.preventDefault()
        setEditing(a.id)
      } else if (k === "r") decide(a, "tolak")
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [items, focus, busy, decide])

  useEffect(() => {
    if (focus >= items.length && items.length) setFocus(items.length - 1)
  }, [items.length, focus])

  const decided = (history?.items ?? []).filter((a) => a.status !== "menunggu").slice(0, 8)

  return (
    <div>
      <PageHeader
        title="Approval"
        description="Draf yang butuh keputusan staf, diurutkan dari yang paling lama menunggu. Teks yang dikirim tetap diperiksa ClaimGuard."
        actions={
          <span className="hidden items-center gap-1.5 text-[12px] text-muted-foreground md:inline-flex">
            <Keyboard className="size-4" /> A setujui · E edit · R tolak · J/K pindah
          </span>
        }
      />
      <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
        <div>
          {!data ? (
            <SkeletonRows rows={4} />
          ) : items.length === 0 ? (
            <Panel>
              <EmptyState title="Antrean kosong" description="Tidak ada draf yang menunggu. AI menangani sisanya dalam batas wewenangnya." />
            </Panel>
          ) : (
            <AnimatePresence initial={false}>
              {items.map((a, i) => (
                <ApprovalCard
                  key={a.id}
                  a={a}
                  focused={i === focus}
                  editing={editing === a.id}
                  onFocus={() => setFocus(i)}
                  onEdit={(v) => setEditing(v ? a.id : null)}
                  onDecide={(aksi, teks) => decide(a, aksi, teks)}
                  busy={busy}
                  error={errors[a.id] ?? null}
                />
              ))}
            </AnimatePresence>
          )}
        </div>
        <aside>
          <Panel className="overflow-hidden">
            <div className="border-b border-line px-4 py-3.5 text-[14.5px] font-semibold">Baru diputuskan</div>
            <ul className="divide-y divide-line">
              {decided.map((a) => (
                <li key={a.id} className="px-4 py-3 text-[13px]">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium">{contactName(a.contact)}</span>
                    <span
                      className={cn(
                        "ml-auto inline-flex h-5 items-center rounded-md px-1.5 text-[11.5px] font-semibold",
                        a.status === "disetujui" ? "bg-ok-bg text-ok" : "bg-blocked-bg text-blocked",
                      )}
                    >
                      {a.status === "disetujui" ? "Disetujui" : "Ditolak"}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[12px] text-subtle-foreground">
                    {a.ditinjau_oleh} · {relativeTime(a.diputus_pada)}
                  </div>
                </li>
              ))}
              {decided.length === 0 && <li className="px-4 py-3 text-[13px] text-muted-foreground">Belum ada keputusan.</li>}
            </ul>
          </Panel>
        </aside>
      </div>
    </div>
  )
}
