"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

import { useRole } from "@/lib/rbac"
import { cn } from "@/lib/utils"

const MENU = [
  { href: "/leads", label: "Daftar", admin: false },
  { href: "/leads/tinjauan", label: "Antrean tinjauan", admin: false },
  { href: "/leads/impor", label: "Impor", admin: true },
  { href: "/leads/skor", label: "Pengaturan skor", admin: true },
]

export function LeadsNav() {
  const pathname = usePathname()
  const { actual } = useRole()
  return (
    <nav aria-label="Menu Leads" className="flex gap-6 overflow-x-auto border-b border-line">
      {MENU.filter((m) => !m.admin || actual === "admin").map((m) => {
        const aktif = pathname === m.href
        return (
          <Link
            key={m.href}
            href={m.href}
            aria-current={aktif ? "page" : undefined}
            className={cn(
              "-mb-px inline-flex h-10 shrink-0 items-center border-b-2 text-[13.5px] transition-colors",
              aktif ? "border-forest-900 font-medium text-forest-900" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {m.label}
          </Link>
        )
      })}
    </nav>
  )
}

export function GalatMuat({ error, onUlang }: { error: unknown; onUlang?: () => void }) {
  const status = error && typeof error === "object" && "status" in error ? (error as { status: number }).status : 0
  const ditolak = status === 403
  return (
    <div role="alert" className={cn("rounded-[12px] border px-4 py-3 text-[13px]", ditolak ? "border-review/30 bg-review-bg text-review" : "border-blocked/30 bg-blocked-bg text-blocked")}>
      <p className="font-medium">{ditolak ? "Anda tidak punya izin membuka bagian ini." : "Data gagal dimuat."}</p>
      {ditolak ? (
        <p className="mt-0.5">Hubungi admin kalau Anda memerlukan akses.</p>
      ) : (
        <p className="mt-0.5">
          {error instanceof Error ? error.message : "Periksa koneksi lalu coba lagi."}
          {onUlang && (
            <button type="button" onClick={onUlang} className="ml-2 font-medium underline">
              Coba lagi
            </button>
          )}
        </p>
      )}
    </div>
  )
}
