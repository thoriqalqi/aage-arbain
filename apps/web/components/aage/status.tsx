"use client"

import { Globe, Hand, MessageCircle, Send, ShieldAlert, ShieldCheck, ShieldX, Sparkles, UserRoundCheck, type LucideIcon } from "lucide-react"
import { motion } from "motion/react"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { channelLabel } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Verdict } from "@/lib/types"

// Status selalu ikon + label (design.md §2.2) — tidak pernah hanya warna.
const VERDICT: Record<Verdict, { label: string; icon: LucideIcon; cls: string }> = {
  allowed: { label: "Diizinkan", icon: ShieldCheck, cls: "bg-ok-bg text-ok" },
  review: { label: "Perlu review", icon: ShieldAlert, cls: "bg-review-bg text-review" },
  blocked: { label: "Diblokir", icon: ShieldX, cls: "bg-blocked-bg text-blocked" },
}

export function VerdictBadge({
  verdict,
  rules,
  size = "sm",
  animate = false,
  prefix,
  className,
}: {
  verdict: Verdict | null | undefined
  rules?: string[]
  size?: "sm" | "md"
  animate?: boolean
  prefix?: string
  className?: string
}) {
  if (!verdict) return null
  const v = VERDICT[verdict]
  const Icon = v.icon
  const badge = (
    <motion.span
      initial={animate ? { scale: 0.96, opacity: 0 } : false}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
      className={cn(
        "inline-flex items-center gap-1 rounded-full font-medium whitespace-nowrap",
        size === "sm" ? "h-6 px-2 text-[12px]" : "h-7 px-2.5 text-[13px]",
        v.cls,
        className,
      )}
    >
      <Icon className={size === "sm" ? "size-3.5" : "size-4"} strokeWidth={1.75} aria-hidden />
      {prefix ? `${prefix} ${v.label.toLowerCase()}` : v.label}
    </motion.span>
  )
  if (!rules?.length) return badge
  return (
    <Tooltip>
      <TooltipTrigger render={<span className="inline-flex" />}>{badge}</TooltipTrigger>
      <TooltipContent>Aturan terpicu: {rules.join(", ")}</TooltipContent>
    </Tooltip>
  )
}

export function ScanningBadge() {
  return (
    <span className="shimmer inline-flex h-6 items-center gap-1 rounded-full px-2 text-[12px] font-medium text-muted-foreground">
      <ShieldCheck className="size-3.5" strokeWidth={1.75} aria-hidden /> Memindai…
    </span>
  )
}

const CONV: Record<string, { label: string; icon: LucideIcon; dot: string; cls: string }> = {
  otomatis: { label: "Dijawab AI", icon: Sparkles, dot: "bg-info", cls: "bg-info-bg text-info" },
  eskalasi: { label: "Menunggu staf", icon: UserRoundCheck, dot: "bg-escalate", cls: "bg-escalate-bg text-escalate" },
  ditahan: { label: "Ditahan", icon: ShieldAlert, dot: "bg-review", cls: "bg-review-bg text-review" },
  ditangani_staf: { label: "Ditangani staf", icon: Hand, dot: "bg-forest-700", cls: "bg-brand-50 text-forest-700" },
}

export function ConversationStatus({ status, compact = false }: { status: string; compact?: boolean }) {
  const s = CONV[status] ?? CONV.otomatis
  const Icon = s.icon
  if (compact) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground">
        <span className={cn("size-2 rounded-full", s.dot)} aria-hidden />
        {s.label}
      </span>
    )
  }
  return (
    <span className={cn("inline-flex h-6 items-center gap-1 rounded-full px-2 text-[12px] font-medium", s.cls)}>
      <Icon className="size-3.5" strokeWidth={1.75} aria-hidden /> {s.label}
    </span>
  )
}

const CHANNEL_ICON: Record<string, LucideIcon> = { whatsapp: MessageCircle, telegram: Send, webchat: Globe }

export function ChannelIcon({ kanal, className }: { kanal: string; className?: string }) {
  const Icon = CHANNEL_ICON[kanal] ?? MessageCircle
  return <Icon className={cn("size-3 text-subtle-foreground", className)} aria-label={channelLabel(kanal)} />
}

export function CostChip({ value, className }: { value: number | null | undefined; className?: string }) {
  const v = value ?? 0
  const text = v === 0 ? "Rp 0" : v < 1 ? `Rp ${v.toLocaleString("id-ID", { maximumFractionDigits: 2 })}` : `Rp ${Math.round(v).toLocaleString("id-ID")}`
  return (
    <span className={cn("inline-flex h-5 items-center rounded-md bg-soft px-1.5 font-mono text-[11px] text-muted-foreground", className)}>
      {text}
    </span>
  )
}

export function Pill({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex h-6 items-center gap-1 rounded-full bg-soft px-2 text-[12px] font-medium text-muted-foreground", className)}>
      {children}
    </span>
  )
}
