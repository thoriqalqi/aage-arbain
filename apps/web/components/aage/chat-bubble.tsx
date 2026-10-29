"use client"

import { Bot, Check, CheckCheck, UserRound } from "lucide-react"
import { motion } from "motion/react"
import { useEffect, useState } from "react"

import { formatTime } from "@/lib/format"
import type { Message } from "@/lib/types"
import { cn } from "@/lib/utils"

import { SourceChip } from "./source-chip"
import { CostChip, VerdictBadge } from "./status"

/** Teks WhatsApp sederhana: *tebal* dan baris baru. */
export function WaText({ text }: { text: string }) {
  const parts = text.split(/(\*[^*\n]+\*)/g)
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("*") && p.endsWith("*") && p.length > 2 ? <strong key={i}>{p.slice(1, -1)}</strong> : <span key={i}>{p}</span>,
      )}
    </>
  )
}

/** Teks muncul per kata (±20ms/kata) untuk pesan AI baru (design.md §9). */
function StreamingText({ text }: { text: string }) {
  const words = text.split(/(\s+)/)
  const [n, setN] = useState(0)
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setN(words.length)
      return
    }
    const id = window.setInterval(() => setN((v) => (v >= words.length ? v : v + 2)), 20)
    return () => window.clearInterval(id)
  }, [words.length])
  return <WaText text={words.slice(0, n).join("")} />
}

export function TypingBubble() {
  return (
    <div className="flex justify-start">
      <div className="flex items-center gap-1 rounded-2xl rounded-bl-md bg-brand-100 px-4 py-3" aria-label="AI sedang mengetik">
        <span className="typing-dot size-1.5 rounded-full bg-forest-700" />
        <span className="typing-dot size-1.5 rounded-full bg-forest-700" />
        <span className="typing-dot size-1.5 rounded-full bg-forest-700" />
      </div>
    </div>
  )
}

/** Bubble gaya WhatsApp: pembeli putih, AI biru lembut, staf putih bergaris navy (design.md §7.2). */
export function ChatBubble({
  message,
  stream = false,
  showMeta = true,
  compact = false,
}: {
  message: Message
  stream?: boolean
  showMeta?: boolean
  compact?: boolean
}) {
  const inbound = message.arah === "masuk"
  const staff = message.pengirim === "staf"
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
      className={cn("flex", inbound ? "justify-start" : "justify-end")}
    >
      <div className={cn("max-w-[85%] space-y-1.5", compact ? "" : "md:max-w-[75%]")}>
        <div
          className={cn(
            "rounded-2xl px-3.5 py-2.5 leading-[21px] whitespace-pre-wrap shadow-xs",
            inbound && "rounded-bl-md border border-line bg-white",
            !inbound && !staff && "rounded-br-md bg-brand-100 text-forest-950",
            staff && "rounded-br-md border border-brand-200/70 bg-[color-mix(in_oklab,var(--brand-200)_28%,white)]",
          )}
        >
          {!inbound && (
            <div className="mb-1 flex items-center gap-1 text-[11px] font-semibold tracking-wide text-forest-700 uppercase">
              {staff ? <UserRound className="size-3" aria-hidden /> : <Bot className="size-3" aria-hidden />}
              {staff ? "Staf" : "Asisten AI"}
            </div>
          )}
          {stream ? <StreamingText text={message.teks} /> : <WaText text={message.teks} />}
          <div className="mt-1 flex items-center justify-end gap-1 text-[11px] text-subtle-foreground">
            {formatTime(message.waktu)}
            {!inbound &&
              (message.status_kirim === "terkirim" ? (
                <CheckCheck className="size-3.5 text-brand-500" aria-label="Terkirim" />
              ) : (
                <Check className="size-3.5" aria-label={message.status_kirim} />
              ))}
          </div>
        </div>
        {showMeta && !inbound && (message.verdict || message.sumber?.length > 0) && (
          <div className={cn("flex flex-wrap items-center gap-1.5", inbound ? "" : "justify-end")}>
            <VerdictBadge verdict={message.verdict} />
            {message.sumber
              ?.filter((s) => s.chunk_id || s.jenis === "pricing_rules" || s.jenis === "order_draft")
              .slice(0, 3)
              .map((s, i) => <SourceChip key={i} source={s} />)}
            {message.biaya_rp > 0 && <CostChip value={message.biaya_rp} />}
          </div>
        )}
      </div>
    </motion.div>
  )
}
