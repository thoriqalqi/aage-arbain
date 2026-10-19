import { Inbox } from "lucide-react"

import { cn } from "@/lib/utils"

/** Empty state: ikon dalam kotak lembut + kalimat + satu aksi. */
export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: string
  description?: string
  action?: React.ReactNode
  icon?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2.5 px-6 py-12 text-center", className)}>
      <span className="flex size-12 items-center justify-center rounded-xl border border-line bg-blue-50 text-navy-700 [&_svg]:size-5" aria-hidden>
        {icon ?? <Inbox />}
      </span>
      <p className="mt-1 font-semibold">{title}</p>
      {description && <p className="max-w-sm text-[13px] text-muted-foreground">{description}</p>}
      {action}
    </div>
  )
}

export function SkeletonRows({ rows = 5, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="shimmer h-10 rounded-lg" />
      ))}
    </div>
  )
}
