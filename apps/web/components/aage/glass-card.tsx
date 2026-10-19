import { cn } from "@/lib/utils"

export function GlassCard({
  tone = "light",
  sheen = false,
  strong = false,
  className,
  ...props
}: React.ComponentProps<"div"> & { tone?: "light" | "dark"; sheen?: boolean; strong?: boolean }) {
  return (
    <div
      className={cn(tone === "dark" ? "glass-dark" : "glass", strong && "glass-strong", sheen && "glass-sheen", className)}
      {...props}
    />
  )
}

/** Permukaan putih solid untuk tabel/data padat (glass tidak dipakai agar teks tajam). */
export function Surface({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("rounded-lg border bg-card shadow-xs", className)} {...props} />
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl leading-8 font-[650] tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <h2 className="text-base leading-6 font-semibold">{children}</h2>
      {aside}
    </div>
  )
}
