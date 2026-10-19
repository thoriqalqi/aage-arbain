import { cn } from "@/lib/utils"

/** Kartu putih solid bergaris tipis — permukaan utama dashboard. */
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
}: {
  title: string
  description?: string
  actions?: React.ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[22px] leading-8 font-semibold tracking-tight text-foreground">{title}</h1>
        {description && <p className="mt-0.5 max-w-3xl text-[13.5px] text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

/** Judul kartu: ikon kecil dalam kotak + judul, aksi di kanan (gaya referensi). */
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
      <div className="flex min-w-0 items-center gap-2.5">
        {icon && (
          <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-line bg-soft text-navy-900 [&_svg]:size-4">
            {icon}
          </span>
        )}
        <h2 className="truncate text-[14.5px] font-semibold text-foreground">{title}</h2>
      </div>
      {aside && <div className="flex shrink-0 items-center gap-2">{aside}</div>}
    </div>
  )
}

export function SectionTitle({ children, aside }: { children: React.ReactNode; aside?: React.ReactNode }) {
  return <CardHeader title={children} aside={aside} className="mb-4" />
}
