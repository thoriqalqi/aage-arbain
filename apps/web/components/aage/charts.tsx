"use client"

import { TrendingDown, TrendingUp } from "lucide-react"
import { animate, motion, useMotionValue, useTransform } from "motion/react"
import { useEffect, useRef } from "react"
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import { Tooltip as UiTooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatDay, formatNum, formatPct } from "@/lib/format"
import type { ScoreReason } from "@/lib/types"
import { cn } from "@/lib/utils"

import { GlassCard } from "./glass-card"

/** Angka KPI count-up dari nilai sebelumnya (600ms, design.md §9). */
export function CountUp({ value, format = formatNum }: { value: number; format?: (v: number) => string }) {
  const mv = useMotionValue(value)
  const text = useTransform(mv, (v) => format(v))
  const first = useRef(true)
  useEffect(() => {
    if (first.current) {
      first.current = false
      mv.set(0)
    }
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const controls = animate(mv, value, { duration: reduce ? 0 : 0.6, ease: [0.22, 1, 0.36, 1] })
    return () => controls.stop()
  }, [value, mv])
  return <motion.span>{text}</motion.span>
}

function Sparkline({ data, color = "var(--chart-1)" }: { data: number[]; color?: string }) {
  const points = data.map((v, i) => ({ i, v }))
  const id = useRef(`spark-${Math.random().toString(36).slice(2, 8)}`).current
  return (
    <div className="h-10 w-28" aria-hidden>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.25} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area type="monotone" dataKey="v" stroke={color} strokeWidth={2} fill={`url(#${id})`} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

export function KpiTile({
  label,
  value,
  format,
  delta,
  deltaGoodWhenUp = true,
  deltaFormat = formatNum,
  spark,
  hint,
  icon,
}: {
  label: string
  value: number
  format?: (v: number) => string
  delta?: number | null
  deltaGoodWhenUp?: boolean
  deltaFormat?: (v: number) => string
  spark?: number[]
  hint?: string
  icon?: React.ReactNode
}) {
  const up = (delta ?? 0) > 0
  const good = delta == null || delta === 0 ? null : up === deltaGoodWhenUp
  return (
    <GlassCard sheen className="lift flex flex-col justify-between gap-3 p-5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-medium tracking-[0.02em] text-muted-foreground">{label}</span>
        {icon}
      </div>
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="tabular text-[32px] leading-10 font-[650] tracking-tight">
            <CountUp value={value} format={format} />
          </div>
          <div className="mt-1 flex items-center gap-1.5 text-[12px]">
            {delta != null && delta !== 0 ? (
              <span className={cn("inline-flex items-center gap-0.5 font-medium", good ? "text-ok" : "text-blocked")}>
                {up ? <TrendingUp className="size-3.5" aria-hidden /> : <TrendingDown className="size-3.5" aria-hidden />}
                {up ? "+" : ""}
                {deltaFormat(delta)}
              </span>
            ) : (
              <span className="text-subtle-foreground">stabil</span>
            )}
            {hint && <span className="text-subtle-foreground">· {hint}</span>}
          </div>
        </div>
        {spark && spark.length > 1 && <Sparkline data={spark} />}
      </div>
    </GlassCard>
  )
}

/** Bar skor 0–100 gradient emerald + tooltip alasan skor (design.md §7.2). */
export function ScoreBar({ score, reasons, className }: { score: number; reasons?: ScoreReason[]; className?: string }) {
  const bar = (
    <div className={cn("flex items-center gap-2", className)}>
      <div className="h-2 w-24 overflow-hidden rounded-full bg-cream-200" role="meter" aria-valuenow={score} aria-valuemin={0} aria-valuemax={100} aria-label="Skor prospek">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${score}%` }}
          transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
          className="h-full rounded-full bg-[linear-gradient(90deg,var(--mint-glow),var(--emerald-500),var(--emerald-900))]"
        />
      </div>
      <span className="tabular w-7 text-right text-[13px] font-semibold">{score}</span>
    </div>
  )
  if (!reasons?.length) return bar
  return (
    <UiTooltip>
      <TooltipTrigger render={<span className="inline-flex" />}>{bar}</TooltipTrigger>
      <TooltipContent className="max-w-xs">
        <ul className="space-y-0.5">
          {reasons.map((r) => (
            <li key={r.faktor}>
              +{r.poin}/{r.maks} {r.faktor}: {r.keterangan}
            </li>
          ))}
        </ul>
      </TooltipContent>
    </UiTooltip>
  )
}

/** Funnel lead: bar horizontal proporsional + konversi antar tahap di antara bar (design.md §11). */
export function FunnelChart({ data }: { data: { tahap: string; nilai: number; konversi_persen: number | null }[] }) {
  const max = Math.max(1, ...data.map((d) => d.nilai))
  const colors = ["var(--emerald-900)", "var(--emerald-700)", "var(--emerald-500)", "var(--champagne-600)", "var(--mist-blue)"]
  return (
    <div className="space-y-1">
      {data.map((d, i) => (
        <div key={d.tahap}>
          {i > 0 && (
            <div className="py-0.5 pl-36 text-[11px] text-subtle-foreground">
              {d.konversi_persen != null ? `↓ ${formatPct(d.konversi_persen)} konversi` : "↓"}
            </div>
          )}
          <div className="flex items-center gap-3">
            <span className="w-32 shrink-0 text-[13px] text-muted-foreground">{d.tahap}</span>
            <div className="relative h-8 flex-1">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${Math.max(2, (d.nilai / max) * 100)}%` }}
                transition={{ duration: 0.6, delay: i * 0.05, ease: [0.22, 1, 0.36, 1] }}
                className="h-full rounded-md"
                style={{ background: colors[i % colors.length] }}
              />
            </div>
            <span className="tabular w-10 text-right font-semibold">{d.nilai}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

function GlassTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="glass glass-strong !rounded-md px-3 py-2 text-[12px]">
      <div className="mb-1 text-muted-foreground">{label ? formatDay(label) : ""}</div>
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="size-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="tabular ml-auto font-semibold">{formatNum(p.value)}</span>
        </div>
      ))}
    </div>
  )
}

/** Volume chat harian: otomatis vs eskalasi (maks 4 seri, grid horizontal saja). */
export function VolumeChart({ data }: { data: { tanggal: string; otomatis: number; eskalasi: number; diblokir: number }[] }) {
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }} barCategoryGap="28%">
          <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
          <XAxis dataKey="tanggal" tickFormatter={(v) => formatDay(v)} tickLine={false} axisLine={false} tick={{ fill: "var(--chart-axis)", fontSize: 11 }} />
          <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--chart-axis)", fontSize: 11 }} />
          <Tooltip content={<GlassTooltip />} cursor={{ fill: "var(--cream-100)" }} />
          <Bar dataKey="otomatis" name="Dijawab otomatis" stackId="a" fill="var(--chart-1)" radius={[0, 0, 0, 0]} />
          <Bar dataKey="eskalasi" name="Eskalasi/ditahan" stackId="a" fill="var(--chart-3)" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
