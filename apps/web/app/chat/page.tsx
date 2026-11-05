"use client"

import { ArrowLeft, Eye, EyeOff, Send, ShieldCheck } from "lucide-react"
import { AnimatePresence } from "motion/react"
import { useCallback, useEffect, useRef, useState } from "react"

import { ChatBubble, TypingBubble } from "@/components/aage/chat-bubble"
import { ApiError, api } from "@/lib/api"
import type { Message } from "@/lib/types"
import { cn } from "@/lib/utils"

const SUGGESTIONS = [
  "ada produk untuk stamina?",
  "harga 50 karton berapa?",
  "Bisa diskon 30%?",
  "bisa sembuhkan hipertensi?",
  "pesan ulang seperti bulan lalu",
  "pengiriman ke Solo berapa hari?",
]

function sessionId(): string {
  const key = "aage.chat.session"
  try {
    const existing = window.localStorage.getItem(key)
    if (existing) return existing
    const fresh = `demo${Math.random().toString(36).slice(2, 10)}`
    window.localStorage.setItem(key, fresh)
    return fresh
  } catch {
    return `demo${Math.random().toString(36).slice(2, 10)}`
  }
}

type SimResponse = { balasan: Message[]; keputusan: string; verdict_masuk: string | null }

export default function WebChatPage() {
  const [session, setSession] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [streamIds, setStreamIds] = useState<Set<number>>(new Set())
  const [text, setText] = useState("")
  const [sending, setSending] = useState(false)
  const [evidence, setEvidence] = useState(false)
  const bottom = useRef<HTMLDivElement>(null)
  const lastId = useRef(0)
  const loaded = useRef(false)

  useEffect(() => {
    setSession(sessionId())
  }, [])

  const poll = useCallback(async () => {
    if (!session) return
    const res = await api<{ pesan: Message[] }>(`/api/chat/simulate/${session}/messages?after_id=${lastId.current}`)
    if (res.pesan.length) {
      lastId.current = res.pesan[res.pesan.length - 1].id
      setMessages((prev) => {
        const seen = new Set(prev.map((m) => m.id))
        const fresh = res.pesan.filter((m) => !seen.has(m.id))
        if (fresh.length && loaded.current) {
          setStreamIds((s) => new Set([...s, ...fresh.filter((m) => m.arah === "keluar").map((m) => m.id)]))
        }
        return [...prev, ...fresh]
      })
    }
    loaded.current = true
  }, [session])

  useEffect(() => {
    poll().catch(() => undefined)
    const id = window.setInterval(() => poll().catch(() => undefined), 3000)
    return () => window.clearInterval(id)
  }, [poll])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [messages, sending])

  async function send(body: string) {
    const value = body.trim()
    if (!value || !session || sending) return
    setText("")
    setSending(true)
    const optimistic: Message = {
      id: -Date.now(), arah: "masuk", pengirim: "pembeli", teks: value, status_kirim: "diterima", verdict: null,
      verdict_label: null, sumber: [], biaya_rp: 0, trace_id: null, waktu: new Date().toISOString(),
    }
    setMessages((m) => [...m, optimistic])
    try {
      await api<SimResponse>("/api/chat/simulate", { method: "POST", json: { session, text: value } })
      setMessages((m) => m.filter((x) => x.id !== optimistic.id))
      await poll()
    } catch (err) {
      const teks = err instanceof ApiError && err.status === 403 ? "Peran Anda tidak memiliki izin memakai simulator ini." : "Maaf, koneksi terputus. Coba kirim ulang ya, Kak."
      setMessages((m) => [...m, { ...optimistic, id: -Date.now() - 1, arah: "keluar", pengirim: "ai", teks }])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex min-h-dvh justify-center bg-soft">
      <div className="flex h-dvh w-full max-w-[480px] flex-col bg-canvas shadow-lg">
        <header className="brand-gradient flex h-16 shrink-0 items-center gap-3 px-3">
          <ArrowLeft className="size-5 text-white/70" aria-hidden />
          <span className="glass-on-dark flex size-10 items-center justify-center rounded-full text-[15px] font-bold">A</span>
          <div className="min-w-0 flex-1">
            <div className="truncate font-semibold text-white">CV Arba&apos;in · Penjualan</div>
            <div className="flex items-center gap-1 text-[12px] text-white/70">
              <ShieldCheck className="size-3.5 text-brand-200" aria-hidden /> Asisten AI 24 jam · diperiksa ClaimGuard
            </div>
          </div>
          <button
            type="button"
            onClick={() => setEvidence((v) => !v)}
            className="flex size-11 items-center justify-center rounded-full text-white/80 hover:bg-white/10"
            aria-label={evidence ? "Sembunyikan bukti" : "Tampilkan bukti (mode demo)"}
            title="Mode demo: tampilkan verdict ClaimGuard & sumber"
          >
            {evidence ? <Eye className="size-5" /> : <EyeOff className="size-5" />}
          </button>
        </header>

        <div className="scrollbar-thin flex-1 space-y-3 overflow-y-auto px-3 py-4">
          <div className="mx-auto w-fit rounded-md bg-white/80 px-3 py-1 text-center text-[11.5px] text-muted-foreground shadow-xs">
            Web chat cadangan · pipeline sama dengan WhatsApp
          </div>
          <AnimatePresence initial={false}>
            {messages.map((m) => (
              <ChatBubble key={m.id} message={m} stream={streamIds.has(m.id)} showMeta={evidence} compact />
            ))}
          </AnimatePresence>
          {sending && <TypingBubble />}
          <div ref={bottom} />
        </div>

        {messages.length < 2 && (
          <div className="scrollbar-thin flex gap-2 overflow-x-auto px-3 pb-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => send(s)}
                className="btn-glass h-9 shrink-0 rounded-full px-3 text-[13px] text-forest-900"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault()
            send(text)
          }}
          className="glass glass-strong m-3 mt-1 flex items-center gap-2 !rounded-full p-1.5 pl-4"
        >
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Ketik pesan…"
            aria-label="Pesan"
            className="h-11 min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-subtle-foreground"
          />
          <button
            type="submit"
            disabled={!text.trim() || sending}
            className={cn(
              "btn-liquid flex size-11 items-center justify-center rounded-full transition-opacity",
              (!text.trim() || sending) && "opacity-50",
            )}
            aria-label="Kirim"
          >
            <Send className="size-5" />
          </button>
        </form>
      </div>
    </div>
  )
}
