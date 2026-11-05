"use client"

import { Bot, ClipboardCheck, Hand, MapPinned, PanelRight, Search, Send, Store } from "lucide-react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"
import { Suspense, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { ChatBubble } from "@/components/aage/chat-bubble"
import { ContactEditor, InlineApprovals, SaranAI, WaitBadge, WindowNotice } from "@/components/aage/inbox-panels"
import { EmptyState, SkeletonRows } from "@/components/aage/empty-state"
import { LedgerTimeline } from "@/components/aage/ledger-timeline"
import { PageHeader } from "@/components/aage/panel"
import { ChannelIcon, ConversationStatus, CostChip, Pill, VerdictBadge } from "@/components/aage/status"
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { ApiError, api, fetcher } from "@/lib/api"
import { channelLabel, contactName, formatRp, relativeTime } from "@/lib/format"
import { INTENT_LABEL, type CheckResult, type ConversationDetail, type ConversationSummary } from "@/lib/types"
import { cn } from "@/lib/utils"

const FILTERS = [
  { key: "", label: "Semua" },
  { key: "otomatis", label: "Dijawab AI" },
  { key: "eskalasi", label: "Menunggu staf" },
  { key: "ditahan", label: "Ditahan" },
  { key: "ditangani_staf", label: "Ditangani staf" },
]

function useIsWide(px: number) {
  const [wide, setWide] = useState(true)
  useEffect(() => {
    const mq = window.matchMedia(`(min-width: ${px}px)`)
    const on = () => setWide(mq.matches)
    on()
    mq.addEventListener("change", on)
    return () => mq.removeEventListener("change", on)
  }, [px])
  return wide
}

function ConversationList({ selected, onSelect }: { selected: number | null; onSelect: (id: number) => void }) {
  const [filter, setFilter] = useState("")
  const [q, setQ] = useState("")
  const { data, error } = useSWR<{ items: ConversationSummary[]; jumlah_per_status: Record<string, number> }>(
    `/api/conversations${filter ? `?status=${filter}` : ""}`,
    fetcher,
    { refreshInterval: 5000 },
  )
  const items = useMemo(
    () => (data?.items ?? []).filter((c) => !q || `${c.contact.nama_toko ?? ""} ${c.contact.nama_wa ?? ""} ${c.contact.wa_number ?? ""} ${c.pesan_terakhir?.teks ?? ""}`.toLowerCase().includes(q.toLowerCase())),
    [data, q],
  )
  return (
    <div className="flex h-full flex-col">
      <div className="space-y-3 border-b p-3">
        <label className="flex h-9 items-center gap-2 rounded-md border border-line bg-white px-2.5">
          <Search className="size-4 text-subtle-foreground" aria-hidden />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari toko atau pesan" className="min-w-0 flex-1 bg-transparent text-[13px] outline-none" aria-label="Cari percakapan" />
        </label>
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter status">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              role="tab"
              aria-selected={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={cn(
                "h-7 rounded-full px-2.5 text-[12px] font-medium transition-colors",
                filter === f.key ? "bg-primary text-primary-foreground" : "bg-soft text-muted-foreground hover:bg-line",
              )}
            >
              {f.label}
              {f.key && data?.jumlah_per_status?.[f.key] ? <span className="ml-1 opacity-70">{data.jumlah_per_status[f.key]}</span> : null}
            </button>
          ))}
        </div>
      </div>
      <div className="scrollbar-thin flex-1 overflow-y-auto">
        {!data ? (
          error ? (
            <EmptyState title="Daftar percakapan belum termuat" description="Server lambat atau terputus. Halaman ini mencoba lagi otomatis." />
          ) : (
            <SkeletonRows className="p-3" rows={8} />
          )
        ) : items.length === 0 ? (
          <EmptyState title="Belum ada percakapan" description="Pesan WhatsApp atau web chat akan muncul di sini." />
        ) : (
          <ul>
            {items.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => onSelect(c.id)}
                  className={cn(
                    "flex w-full gap-3 border-b border-line/70 px-3 py-3 text-left transition-colors hover:bg-soft/70",
                    selected === c.id && "bg-brand-50",
                  )}
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-line text-[13px] font-semibold text-forest-900">
                    {(c.contact.nama_toko || "P").slice(0, 1)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate font-medium">{contactName(c.contact)}</span>
                      <span className="ml-auto shrink-0 text-[11px] text-subtle-foreground">{relativeTime(c.diperbarui_pada)}</span>
                    </span>
                    <span className="line-clamp-1 text-[12.5px] text-muted-foreground">{c.pesan_terakhir?.teks}</span>
                    <span className="mt-1 flex items-center gap-2">
                      <ConversationStatus status={c.status} compact />
                      <ChannelIcon kanal={c.kanal} />
                      {c.approval_menunggu > 0 && <WaitBadge since={c.menunggu_sejak} className="ml-auto" />}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function ContextPanel({ conv, onChanged }: { conv: ConversationDetail; onChanged: () => void }) {
  const c = conv.contact
  return (
    <div className="scrollbar-thin h-full space-y-5 overflow-y-auto p-4">
      <section>
        <h3 className="mb-2 text-[12px] font-medium tracking-[0.02em] text-muted-foreground">Profil toko</h3>
        <div className="space-y-1">
          <div className="flex items-center gap-2 font-semibold">
            <Store className="size-4 text-forest-700" /> {c.nama_toko || "Belum diketahui"}
          </div>
          {c.nama_wa && <div className="text-[13px] text-muted-foreground">Profil {channelLabel(c.channel)}: {c.nama_wa}</div>}
          <div className="font-mono text-[12px] text-muted-foreground">
            {c.wa_number ?? `${channelLabel(c.channel)} ID ${c.external_user_id}`}
          </div>
          {c.alamat && <div className="text-[13px] text-muted-foreground">{c.alamat}</div>}
          <div className="flex flex-wrap gap-1.5 pt-1">
            {c.tipe_toko && <Pill>{c.tipe_toko}</Pill>}
            <Pill>{c.opt_in ? "Opt-in pengingat" : "Belum opt-in"}</Pill>
            <Pill>Biaya AI {formatRp(conv.biaya_total_rp, { decimals: true })}</Pill>
          </div>
          <div className="pt-2">
            <ContactEditor contact={c} onSaved={onChanged} />
          </div>
        </div>
      </section>
      {conv.memori && (
        <section>
          <h3 className="mb-2 text-[12px] font-medium tracking-[0.02em] text-muted-foreground">Ringkasan percakapan</h3>
          <ul className="space-y-1 text-[13px] text-muted-foreground">
            {conv.memori.split(" · ").map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </section>
      )}
      {conv.prospek && (
        <Link href={`/leads?prospek=${conv.prospek.id}`} className="flex items-center gap-2 rounded-md bg-brand-50 px-3 py-2 text-[13px] font-medium text-forest-700">
          <MapPinned className="size-4" /> Dari Leads: {conv.prospek.nama} · skor {conv.prospek.skor} · {conv.prospek.status}
        </Link>
      )}
      {conv.pesanan_terakhir && (
        <section>
          <h3 className="mb-2 text-[12px] font-medium tracking-[0.02em] text-muted-foreground">Pesanan terakhir #{conv.pesanan_terakhir.id}</h3>
          <ul className="space-y-1 text-[13px]">
            {conv.pesanan_terakhir.item.map((it) => (
              <li key={it.sku} className="flex justify-between gap-2">
                <span className="truncate">{it.nama} × {it.qty}</span>
                <span className="tabular text-muted-foreground">{formatRp(it.subtotal)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-1 text-[12px] text-subtle-foreground">Status: {conv.pesanan_terakhir.status}</div>
        </section>
      )}
      {conv.approvals.some((a) => a.status === "menunggu") && (
        <div className="flex items-center gap-2 rounded-md bg-escalate-bg px-3 py-2 text-[13px] font-medium text-escalate">
          <ClipboardCheck className="size-4" /> {conv.approvals.filter((a) => a.status === "menunggu").length} draf menunggu — putuskan langsung di chat
        </div>
      )}
      <section>
        <h3 className="mb-3 text-[12px] font-medium tracking-[0.02em] text-muted-foreground">Ledger percakapan</h3>
        <LedgerTimeline events={conv.ledger.slice(-24)} dense />
        <Link href={`/compliance?tab=ledger&conversation_id=${conv.id}`} className="text-[13px] font-medium text-forest-700 hover:underline">
          Lihat semua event →
        </Link>
      </section>
    </div>
  )
}

function ChatPanel({ id, onOpenContext, showContextButton }: { id: number; onOpenContext: () => void; showContextButton: boolean }) {
  const { data, mutate } = useSWR<ConversationDetail>(`/api/conversations/${id}`, fetcher, { refreshInterval: 4000 })
  const [text, setText] = useState("")
  const [sending, setSending] = useState(false)
  const [blocked, setBlocked] = useState<CheckResult | null>(null)
  const [toggling, setToggling] = useState(false)
  const kolomChat = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (kolomChat.current) kolomChat.current.scrollTop = kolomChat.current.scrollHeight
  }, [id, data?.pesan.length])

  async function send() {
    if (!text.trim()) return
    setSending(true)
    setBlocked(null)
    try {
      await api(`/api/conversations/${id}/reply`, { method: "POST", json: { text } })
      setText("")
      toast.success("Terkirim ke pembeli")
      mutate()
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        const cg = (err.detail as { claimguard?: CheckResult })?.claimguard
        if (cg) setBlocked(cg)
        toast.error(err.message)
      } else toast.error("Gagal mengirim")
    } finally {
      setSending(false)
    }
  }

  async function toggleTakeOver() {
    if (!data) return
    setToggling(true)
    const handled = data.status === "ditangani_staf"
    try {
      await api(`/api/conversations/${id}/${handled ? "kembalikan" : "ambil-alih"}`, { method: "POST" })
      toast.success(handled ? "AI kembali menjawab percakapan ini" : "Anda memegang percakapan ini — AI hanya memberi saran")
      mutate()
    } catch {
      toast.error("Gagal mengubah penanganan")
    } finally {
      setToggling(false)
    }
  }

  if (!data) return <SkeletonRows className="p-4" rows={6} />
  const handled = data.status === "ditangani_staf"
  const inboundVerdicts = data.ledger.filter((e) => e.tipe_event === "claimguard_inbound")
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold">{contactName(data.contact)}</div>
          <div className="flex flex-wrap items-center gap-x-2 text-[12px] whitespace-nowrap text-muted-foreground">
            <ConversationStatus status={data.status} compact />
            <span className="hidden sm:inline">· {channelLabel(data.kanal)}</span>
            {data.intent_terakhir && <span className="hidden sm:inline">· {INTENT_LABEL[data.intent_terakhir] ?? data.intent_terakhir}</span>}
            {handled && data.ditangani_oleh && <span>· oleh {data.ditangani_oleh}</span>}
          </div>
        </div>
        <AButton
          size="sm"
          variant={handled ? "glass" : "default"}
          disabled={toggling}
          onClick={toggleTakeOver}
          className="shrink-0"
          aria-label={handled ? "Kembalikan ke AI" : "Ambil alih"}
        >
          {handled ? <Bot className="size-3.5" /> : <Hand className="size-3.5" />}
          <span className="hidden sm:inline">{handled ? "Kembalikan ke AI" : "Ambil alih"}</span>
        </AButton>
        <CostChip value={data.biaya_total_rp} className="hidden sm:inline-flex" />
        {showContextButton && (
          <AButton variant="ghost" size="icon" onClick={onOpenContext} aria-label="Panel konteks">
            <PanelRight className="size-4" />
          </AButton>
        )}
      </div>
      <div ref={kolomChat} className="scrollbar-thin flex-1 space-y-3 overflow-y-auto bg-canvas p-4">
        {data.pesan.map((m) => (
          <div key={m.id}>
            <ChatBubble message={m} />
            {m.arah === "masuk" &&
              inboundVerdicts
                .filter((e) => e.trace_id === m.trace_id)
                .map((e) => (
                  <div key={e.id} className="mt-1 flex items-center gap-1.5 pl-1 text-[12px] text-muted-foreground">
                    <VerdictBadge verdict={e.verdict} rules={e.aturan_terpicu} prefix="Klaim yang diminta:" />
                  </div>
                ))}
          </div>
        ))}
      </div>
      <InlineApprovals key={id} approvals={data.approvals} onDone={() => mutate()} />
      {handled && <SaranAI saran={data.saran_ai} onUse={setText} />}
      <WindowNotice jendela={data.jendela} />
      {blocked && (
        <div className="mx-3 mb-2 rounded-lg bg-blocked-bg p-3 text-[13px] text-blocked">
          <div className="flex items-center gap-2 font-semibold">
            <VerdictBadge verdict={blocked.verdict} rules={blocked.rules_triggered} /> Balasan tidak dikirim
          </div>
          {blocked.safe_text && (
            <button className="mt-1 text-left underline" onClick={() => setText(blocked.safe_text)}>
              Pakai versi aman: “{blocked.safe_text.slice(0, 140)}…”
            </button>
          )}
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault()
          send()
        }}
        className="glass glass-strong m-3 mt-0 flex items-end gap-2 !rounded-lg p-2"
      >
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          placeholder={handled ? "Balas sebagai staf — tetap diperiksa ClaimGuard" : "Membalas = mengambil alih percakapan dari AI · tetap diperiksa ClaimGuard"}
          className="min-h-11 flex-1 resize-none bg-transparent px-2 py-1.5 text-[14px] outline-none placeholder:text-subtle-foreground"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send()
          }}
          aria-label="Balasan staf"
        />
        <AButton type="submit" disabled={sending || !text.trim()}>
          <Send className="size-4" /> Kirim
        </AButton>
      </form>
    </div>
  )
}

function InboxInner() {
  const router = useRouter()
  const params = useSearchParams()
  const selected = params.get("id") ? Number(params.get("id")) : null
  const wide = useIsWide(1280)
  const medium = useIsWide(768)
  const [ctxOpen, setCtxOpen] = useState(false)
  const { data: detail, mutate: refreshDetail } = useSWR<ConversationDetail>(selected ? `/api/conversations/${selected}` : null, fetcher, { refreshInterval: 4000 })
  const select = (id: number) => router.replace(`/inbox?id=${id}`)

  const chat = selected ? (
    <ChatPanel id={selected} onOpenContext={() => setCtxOpen(true)} showContextButton={!wide} />
  ) : (
    <EmptyState title="Pilih percakapan" description="Klik salah satu chat untuk melihat bubble, verdict ClaimGuard, dan sumbernya." className="h-full" />
  )

  return (
    <>
    <PageHeader title="Inbox" description="Percakapan dari WhatsApp, Telegram, dan simulator. Jawaban otomatis hanya bersumber dari Knowledge Base dan selalu diperiksa ClaimGuard." />
    <div className="panel h-[calc(100dvh-13rem)] min-h-[520px] overflow-hidden">
      {!medium ? (
        selected ? (
          <div className="flex h-full flex-col">
            <button onClick={() => router.replace("/inbox")} className="border-b px-4 py-2 text-left text-[13px] text-forest-700">← Semua percakapan</button>
            <div className="min-h-0 flex-1">{chat}</div>
          </div>
        ) : (
          <ConversationList selected={selected} onSelect={select} />
        )
      ) : (
        <ResizablePanelGroup orientation="horizontal">
          <ResizablePanel defaultSize="28" minSize="20">
            <ConversationList selected={selected} onSelect={select} />
          </ResizablePanel>
          <ResizableHandle withHandle />
          <ResizablePanel defaultSize={wide ? "44" : "72"} minSize="30">
            {chat}
          </ResizablePanel>
          {wide && (
            <>
              <ResizableHandle withHandle />
              <ResizablePanel defaultSize="28" minSize="20">
                {detail ? <ContextPanel conv={detail} onChanged={() => refreshDetail()} /> : <div className="p-4 text-muted-foreground">Panel konteks</div>}
              </ResizablePanel>
            </>
          )}
        </ResizablePanelGroup>
      )}
      <Sheet open={ctxOpen && !wide} onOpenChange={setCtxOpen}>
        <SheetContent side="right" className="w-full bg-card sm:max-w-md">
          <SheetTitle className="px-4 pt-4">Konteks percakapan</SheetTitle>
          {detail && <ContextPanel conv={detail} onChanged={() => refreshDetail()} />}
        </SheetContent>
      </Sheet>
    </div>
    </>
  )
}

export default function InboxPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={8} />}>
      <InboxInner />
    </Suspense>
  )
}
