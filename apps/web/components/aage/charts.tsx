"use client"

import { ArrowDownRight, ArrowUpRight, Info } from "lucide-react"
import { animate, motion, useMotionValue, useTransform } from "motion/react"
import { useEffect, useRef } from "react"
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"

import { Tooltip as UiTooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { formatDay, formatNum, formatPct } from "@/lib/format"
import type { ScoreReason } from "@/lib/types"
import { cn } from "@/lib/utils"

import { Panel } from "./panel"

/** Angka count-up dari nilai sebelumnya (600ms). */
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

/** Pill delta hijau/merah kecil di samping angka (gaya referensi). */
export function DeltaPill({ value, good, format = formatNum }: { value: number | null | undefined; good: boolean | null; format?: (v: number) => string }) {
  if (value == null || value === 0) {
    return <span className="inline-flex h-[22px] items-center rounded-md bg-soft px-1.5 text-[12px] font-medium text-muted-foreground">stabil</span>
  }
  const up = value > 0
  const Icon = up ? ArrowUpRight : ArrowDownRight
  return (
    <span className={cn("inline-flex h-[22px] items-center gap-0.5 rounded-md px-1.5 text-[12px] font-semibold", good ? "bg-ok-bg text-ok" : "bg-blocked-bg text-blocked")}>
      {up ? "+" : ""}
      {format(value)}
      <Icon className="size-3.5" aria-hidden />
    </span>
  )
}

export function KpiTile({
  label,
  value,
  format,
  delta,
  deltaGoodWhenUp = true,
  deltaFormat = formatNum,
  hint,
  icon,
  info,
}: {
  label: string
  value: number
  format?: (v: number) => string
  delta?: number | null
  deltaGoodWhenUp?: boolean
  deltaFormat?: (v: number) => string
  hint?: string
  icon?: React.ReactNode
  info?: string
}) {
  const good = delta == null || delta === 0 ? null : delta > 0 === deltaGoodWhenUp
  return (
    <Panel className="lift flex flex-col gap-4 p-5">
      <div className="flex items-center gap-2.5">
        {icon && (
          <span className="flex size-7 items-center justify-center rounded-lg border border-line bg-soft text-navy-900 [&_svg]:size-4">{icon}</span>
        )}
        <span className="text-[13.5px] font-medium text-foreground">{label}</span>
        {info && (
          <UiTooltip>
            <TooltipTrigger render={<span className="ml-auto inline-flex text-subtle-foreground" />}>
              <Info className="size-4" aria-label="Info" />
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">{info}</TooltipContent>
          </UiTooltip>
        )}
      </div>
      <div>
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="tabular text-[28px] leading-9 font-semibold tracking-tight text-foreground">
            <CountUp value={value} format={format} />
          </span>
          <DeltaPill value={delta} good={good} format={deltaFormat} />
        </div>
        {hint && <div className="mt-1 text-[12.5px] text-subtle-foreground">{hint}</div>}
      </div>
    </Panel>
  )
}

/** Bar skor 0–100 gradient navy → biru + tooltip alasan skor. */
export function ScoreBar({ score, reasons, className }: { score: number; reasons?: ScoreReason[]; className?: string }) {
  const bar = (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-line" role="meter" aria-valuenow={score} aria-valuemin={0} aria-valuemax={100} aria-label="Skor prospek">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${score}%` }}
          transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
          className="h-full rounded-full bg-[linear-gradient(90deg,var(--blue-400),var(--navy-900))]"
        />
      </div>
      <span className="tabular w-7 text-[13px] font-semibold text-navy-900">{score}</span>
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

const FUNNEL_COLORS = ["var(--navy-900)", "var(--navy-700)", "var(--blue-600)", "var(--blue-500)", "var(--blue-400)"]

/** Funnel lead: bar horizontal proporsional + konversi antar tahap. */
export function FunnelChart({ data }: { data: { tahap: string; nilai: number; konversi_persen: number | null }[] }) {
  const max = Math.max(1, ...data.map((d) => d.nilai))
  return (
    <ol className="space-y-3.5">
      {data.map((d, i) => (
        <li key={d.tahap}>
          <div className="mb-1.5 flex items-center justify-between gap-2 text-[13px]">
            <span className="text-muted-foreground">{d.tahap}</span>
            <span className="flex items-center gap-2">
              {d.konversi_persen != null && <span className="text-[11.5px] text-subtle-foreground">{formatPct(d.konversi_persen)}</span>}
              <span className="tabular font-semibold text-foreground">{d.nilai}</span>
            </span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-soft">
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${Math.max(2, (d.nilai / max) * 100)}%` }}
              transition={{ duration: 0.6, delay: i * 0.05, ease: [0.22, 1, 0.36, 1] }}
              className="h-full rounded-full"
              style={{ background: FUNNEL_COLORS[i % FUNNEL_COLORS.length] }}
            />
          </div>
        </li>
      ))}
    </ol>
  )
}

function GlassTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null
  return (
    <div className="glass glass-strong !rounded-[10px] px-3 py-2 text-[12px]">
      {label && /^\d{4}-/.test(label) && <div className="mb-1 text-muted-foreground">{formatDay(label)}</div>}
      {payload.map((p) => (
        <div key={p.name} className="flex items-center gap-2">
          <span className="size-2 rounded-full" style={{ background: p.color }} />
          <span className="text-muted-foreground">{p.name}</span>
          <span className="tabular ml-auto pl-3 font-semibold">{formatNum(p.value)}</span>
        </div>
      ))}
    </div>
  )
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-4 text-[12px] text-muted-foreground">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <span className="size-2 rounded-[3px]" style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  )
}

/** Volume chat harian bertumpuk: otomatis (navy) vs eskalasi/ditahan (biru lembut). */
export function VolumeChart({ data }: { data: { tanggal: string; otomatis: number; eskalasi: number }[] }) {
  return (
    <div className="space-y-3">
      <div className="h-60 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 4, left: -20, bottom: 0 }} barCategoryGap="30%">
            <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
            <XAxis dataKey="tanggal" tickFormatter={(v) => formatDay(v)} tickLine={false} axisLine={false} tick={{ fill: "var(--chart-axis)", fontSize: 11 }} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--chart-axis)", fontSize: 11 }} />
            <Tooltip content={<GlassTooltip />} cursor={{ fill: "var(--blue-50)" }} />
            <Bar dataKey="otomatis" name="Dijawab otomatis" stackId="a" fill="var(--chart-1)" />
            <Bar dataKey="eskalasi" name="Eskalasi/ditahan" stackId="a" fill="var(--chart-4)" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <Legend items={[{ label: "Dijawab otomatis", color: "var(--chart-1)" }, { label: "Eskalasi / ditahan", color: "var(--chart-4)" }]} />
    </div>
  )
}

const HARI = ["Min", "Sen", "Sel", "Rab", "Kam", "Jum", "Sab"]

/** Bar 7 hari: bar tertinggi disorot gradient navy, sisanya abu-biru. */
export function WeekBars({ data }: { data: { tanggal: string; value: number }[] }) {
  const max = Math.max(...data.map((d) => d.value), 0)
  const peak = data.findIndex((d) => d.value === max)
  const rows = data.map((d) => ({ ...d, hari: HARI[new Date(d.tanggal).getDay()] }))
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 24, right: 0, left: 0, bottom: 0 }} barCategoryGap="22%">
          <defs>
            <linearGradient id="aage-peak" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--navy-700)" />
              <stop offset="100%" stopColor="var(--blue-300)" />
            </linearGradient>
          </defs>
          <XAxis dataKey="hari" tickLine={false} axisLine={false} tick={{ fill: "var(--chart-axis)", fontSize: 11.5 }} />
          <Tooltip content={<GlassTooltip />} cursor={false} />
          <Bar dataKey="value" name="Chat" radius={[8, 8, 8, 8]} minPointSize={6}>
            {rows.map((_, i) => (
              <Cell key={i} fill={i === peak && max > 0 ? "url(#aage-peak)" : "var(--chart-muted)"} />
            ))}
            <LabelList
              dataKey="value"
              position="top"
              content={(props) => {
                const { x, y, width, index } = props as { x: number; y: number; width: number; index: number }
                if (index !== peak || max === 0) return null
                return (
                  <text x={x + width / 2} y={y - 8} textAnchor="middle" fontSize={12} fontWeight={600} fill="var(--foreground)">
                    {max}
                  </text>
                )
              }}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
