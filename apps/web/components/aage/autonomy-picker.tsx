"use client"

import { AUTONOMY_LABEL, type AutonomyMode } from "@/lib/agents"
import { cn } from "@/lib/utils"

const MODES: AutonomyMode[] = ["saran", "setujui", "otonom"]

/** Pemilih mode otonomi tiga langkah (Brief §6.4). */
export function AutonomyPicker({
  value,
  onChange,
  allowOtonom = true,
  size = "md",
  label = "Mode otonomi",
}: {
  value: AutonomyMode
  onChange: (m: AutonomyMode) => void
  allowOtonom?: boolean
  size?: "sm" | "md"
  label?: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-[10px] border border-line bg-soft p-0.5">
      {MODES.map((m) => {
        const disabled = m === "otonom" && !allowOtonom
        const on = value === m
        return (
          <button
            key={m}
            type="button"
            role="radio"
            aria-checked={on}
            disabled={disabled}
            title={disabled ? "Otonom hanya untuk jawaban katalog berisiko rendah setelah target akurasi terpenuhi" : undefined}
            onClick={() => onChange(m)}
            className={cn(
              "rounded-[8px] font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-40",
              size === "sm" ? "h-7 px-2.5 text-[12px]" : "h-8 px-3 text-[13px]",
              on ? "bg-card text-forest-900 shadow-xs ring-1 ring-line" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {AUTONOMY_LABEL[m]}
          </button>
        )
      })}
    </div>
  )
}
