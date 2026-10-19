"use client"

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import type { CheckResult, SentenceResult } from "@/lib/types"
import { cn } from "@/lib/utils"

import { VerdictBadge } from "./status"

const MARK: Record<string, string> = { allowed: "mark-ok", review: "mark-review", blocked: "mark-blocked" }

function SentenceMark({ s }: { s: SentenceResult }) {
  return (
    <Popover>
      <PopoverTrigger
        render={
          <mark
            className={cn(
              "cursor-pointer px-0.5 text-inherit transition-[filter] hover:brightness-95 focus-visible:outline-2",
              MARK[s.verdict],
            )}
            tabIndex={0}
          />
        }
      >
        {s.text}
      </PopoverTrigger>
      <PopoverContent className="w-[22rem] space-y-3 text-[13px]">
        <div className="flex items-center justify-between gap-2">
          <VerdictBadge verdict={s.verdict} />
          <span className="text-[11px] text-subtle-foreground">tahap: {s.stage}</span>
        </div>
        {s.rules.length > 0 && (
          <ul className="space-y-1.5">
            {s.rules.map((r) => (
              <li key={r.id}>
                <span className="font-mono text-[11px] text-muted-foreground">{r.id}</span>{" "}
                <span className="font-semibold">{r.label}</span> — “{r.match}”
                <p className="text-muted-foreground">{r.alasan}</p>
              </li>
            ))}
          </ul>
        )}
        {s.matched_claim && (
          <p className="text-muted-foreground">
            Cocok dengan klaim disetujui: <span className="text-foreground">“{s.matched_claim.teks}”</span>
          </p>
        )}
        {s.rules.length === 0 && !s.matched_claim && s.reasons.length > 0 && (
          <p className="text-muted-foreground">{s.reasons[s.reasons.length - 1]}</p>
        )}
        {s.suggestion && (
          <div className="rounded-md bg-ok-bg p-2.5">
            <p className="mb-0.5 text-[11px] font-semibold tracking-wide text-ok uppercase">Saran kalimat aman</p>
            <p>{s.suggestion}</p>
          </div>
        )}
      </PopoverContent>
    </Popover>
  )
}

/** Teks dengan sorotan per kalimat: hijau/kuning/merah lembut; klik → alasan + saran aman (design.md §7.2). */
export function ClaimHighlight({ text, result, showAllowed = true }: { text: string; result: CheckResult; showAllowed?: boolean }) {
  const nodes: React.ReactNode[] = []
  let cursor = 0
  result.sentences.forEach((s, i) => {
    if (s.start > cursor) nodes.push(<span key={`g${i}`}>{text.slice(cursor, s.start)}</span>)
    if (s.verdict === "allowed" && !showAllowed) nodes.push(<span key={i}>{s.text}</span>)
    else nodes.push(<SentenceMark key={i} s={s} />)
    cursor = s.end
  })
  if (cursor < text.length) nodes.push(<span key="tail">{text.slice(cursor)}</span>)
  return <div className="leading-7 whitespace-pre-wrap">{nodes}</div>
}
