import { cn } from "@/lib/utils"

/** Empty state: orb glass kecil + kalimat + satu aksi (design.md §7.2). */
export function EmptyState({
  title,
  description,
  action,
  className,
}: {
  title: string
  description?: string
  action?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-6 py-12 text-center", className)}>
      <div className="relative size-16" aria-hidden>
        <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_30%_30%,var(--mint-glow),var(--emerald-500)_55%,var(--emerald-900))] opacity-80 blur-[1px]" />
        <div className="absolute inset-1 rounded-full bg-[radial-gradient(circle_at_30%_25%,rgb(255_255_255/0.85),transparent_45%)]" />
        <div className="absolute -inset-3 -z-10 rounded-full bg-mint-glow/30 blur-xl" />
      </div>
      <p className="font-semibold">{title}</p>
      {description && <p className="max-w-sm text-muted-foreground">{description}</p>}
      {action}
    </div>
  )
}

export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="shimmer h-10 rounded-md" />
      ))}
    </div>
  )
}
