import { cn } from "@/lib/utils"

/** Kartu putih solid bergaris tipis, radius 16px — permukaan utama dashboard. */
export function Panel({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("panel", className)} {...props} />
}

/** Alias untuk tabel/data padat. */
export function Surface({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("panel overflow-hidden", className)} {...props} />
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  eyebrow?: React.ReactNode
}) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5 text-[12px] font-medium tracking-[0.08em] text-brand-600 uppercase">{eyebrow}</div>}
        <h1 className="text-[28px] leading-9 text-forest-900">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-[13.5px] leading-[22px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** Judul kartu: ikon kecil + judul, aksi di kanan. */
export function CardHeader({
  icon,
  title,
  aside,
  className,
}: {
  icon?: React.ReactNode
  title: React.ReactNode
  aside?: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex items-center justify-between gap-3", className)}>
      <div className="flex min-w-0 items-center gap-2">
        {icon && <span className="flex shrink-0 items-center text-brand-600 [&_svg]:size-4">{icon}</span>}
        <h2 className="truncate text-[14px] font-semibold text-foreground">{title}</h2>
      </div>
      {aside && <div className="flex shrink-0 items-center gap-2">{aside}</div>}
    </div>
  )
}

export function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return <CardHeader title={children} aside={aside} className="mb-4" />
}

/** Label kecil "data contoh" untuk layar yang endpoint API-nya belum siap. */
export function SampleNote({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start gap-2 rounded-xl border border-dashed border-gold-500/50 bg-gold-100/50 px-3.5 py-2.5 text-[12.5px] text-escalate", className)}>
      <span className="mt-[7px] size-1.5 shrink-0 rounded-full bg-gold-500" aria-hidden />
      <span>{children}</span>
    </div>
  )
}
