"use client"

import { cva, type VariantProps } from "class-variance-authority"

import { Button as UiButton } from "@/components/ui/button"
import { cn } from "@/lib/utils"

// Varian tombol design.md §7.2 — membungkus shadcn Button tanpa mengubah components/ui.
const variants = cva(
  "rounded-md font-medium transition-[transform,box-shadow,background-color] duration-150 hover:-translate-y-px hover:shadow-md disabled:hover:translate-y-0 disabled:hover:shadow-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary-hover",
        glass: "glass !rounded-md text-foreground hover:bg-white/80",
        ghost: "bg-transparent text-foreground hover:bg-cream-100 hover:shadow-none hover:translate-y-0",
        outline: "border border-cream-200 bg-card text-foreground hover:bg-cream-100",
        destructive: "bg-blocked-bg text-blocked hover:bg-blocked-bg/80",
        dark: "bg-emerald-950 text-sidebar-foreground hover:bg-emerald-900",
      },
      size: {
        default: "h-9 px-3.5 text-sm gap-2",
        sm: "h-8 px-3 text-[13px] gap-1.5",
        lg: "h-11 px-5 text-[15px] gap-2",
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
