"use client"

import { usePathname, useRouter, useSearchParams } from "next/navigation"

import { cn } from "@/lib/utils"

/** Tab bergaris bawah yang disimpan di ?tab= agar bisa ditautkan langsung. */
export function usePageTab<T extends string>(tabs: readonly T[], fallback: T): [T, (t: T) => void] {
  const params = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const raw = params.get("tab") as T | null
  const current = raw && tabs.includes(raw) ? raw : fallback
  const set = (t: T) => {
    const next = new URLSearchParams()
    if (t !== fallback) next.set("tab", t)
    router.replace(next.size ? `${pathname}?${next}` : pathname, { scroll: false })
  }
  return [current, set]
}

export function PageTabs<T extends string>({
  value,
  onChange,
  items,
  className,
}: {
  value: T
  onChange: (v: T) => void
  items: { value: T; label: React.ReactNode }[]
  className?: string
}) {
  return (
    <div role="tablist" className={cn("mb-6 flex gap-6 overflow-x-auto border-b border-line", className)}>
      {items.map((it) => {
        const on = it.value === value
        return (
          <button
            key={it.value}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => onChange(it.value)}
            className={cn(
              "relative -mb-px inline-flex h-10 shrink-0 items-center gap-2 border-b-2 text-[13.5px] transition-colors",
              on ? "border-forest-900 font-medium text-forest-900" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {it.label}
          </button>
        )
      })}
    </div>
  )
}
