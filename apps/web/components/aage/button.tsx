"use client"

import { cva, type VariantProps } from "class-variance-authority"

import { Button as UiButton } from "@/components/ui/button"
import { cn } from "@/lib/utils"

// Tombol liquid glass: primer = navy berkilau, sekunder = kaca bening. Membungkus shadcn Button.
const variants = cva(
  "rounded-[10px] font-medium focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "btn-liquid hover:bg-transparent",
        glass: "btn-glass hover:bg-transparent",
        outline: "btn-glass hover:bg-transparent",
        ghost: "bg-transparent text-muted-foreground hover:bg-soft hover:text-foreground",
        destructive: "btn-glass !text-blocked hover:bg-transparent",
      },
      size: {
        default: "h-9 px-3.5 text-[13.5px] gap-2",
        sm: "h-8 px-3 text-[13px] gap-1.5",
        lg: "h-11 px-5 text-[14.5px] gap-2",
        icon: "size-9 p-0",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
)

export type AButtonProps = Omit<React.ComponentProps<typeof UiButton>, "variant" | "size"> & VariantProps<typeof variants>

export function AButton({ className, variant, size, ...props }: AButtonProps) {
  return <UiButton className={cn(variants({ variant, size }), className)} {...props} />
}

/** Kelompok tombol segmented (Tabel/Peta, Teks/URL, filter status) dengan gaya kaca. */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: React.ReactNode }[]
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-[10px] border border-line bg-soft p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "inline-flex h-8 items-center gap-1.5 rounded-[8px] px-3 text-[13px] font-medium transition-colors",
            value === o.value ? "btn-glass text-navy-900" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
