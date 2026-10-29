"use client"

import {
  Bell,
  Bot,
  ChartNoAxesCombined,
  Check,
  ClipboardCheck,
  Eye,
  Inbox,
  LayoutDashboard,
  Lock,
  LogOut,
  MapPinned,
  Menu,
  MessageCircle,
  Network,
  PenLine,
  Search,
  Settings2,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react"
import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import useSWR from "swr"

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { clearSession, fetcher, getToken } from "@/lib/api"
import { formatRp } from "@/lib/format"
import { canAccess, ROLE_LABEL, setRolePreview, useRole, type Role } from "@/lib/rbac"
import type { Status } from "@/lib/types"
import { cn } from "@/lib/utils"

type NavItem = { href: string; label: string; icon: LucideIcon; count?: "inbox" | "approval" }

// 11 layar Brief §5 (Login di luar shell). Menu disaring per role lewat lib/rbac.
export const NAV_GROUPS: { label: string | null; items: NavItem[] }[] = [
  {
    label: null,
    items: [
      { href: "/", label: "Ringkasan", icon: LayoutDashboard },
      { href: "/agen", label: "Agen", icon: Bot },
      { href: "/approval", label: "Approval", icon: ClipboardCheck, count: "approval" },
    ],
  },
  {
    label: "Penjualan",
    items: [
      { href: "/leads", label: "Leads", icon: MapPinned },
      { href: "/inbox", label: "Inbox WhatsApp", icon: Inbox, count: "inbox" },
    ],
  },
  {
    label: "Pemasaran",
    items: [
      { href: "/konten", label: "Studio Konten", icon: PenLine },
      { href: "/compliance", label: "Compliance & Ledger", icon: ShieldCheck },
    ],
  },
  {
    label: "Sistem",
    items: [
      { href: "/evaluasi", label: "Evaluasi & Biaya", icon: ChartNoAxesCombined },
      { href: "/pengaturan", label: "Pengaturan", icon: Settings2 },
      { href: "/arsitektur", label: "Arsitektur", icon: Network },
    ],
  },
]
const ALL_ITEMS = NAV_GROUPS.flatMap((g) => g.items)

function navFor(role: Role) {
  return NAV_GROUPS.map((g) => ({ ...g, items: g.items.filter((i) => canAccess(role, i.href)) })).filter((g) => g.items.length)
}

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(href + "/")
}

function useCounts() {
  const { data: ap } = useSWR<{ items: unknown[] }>("/api/approvals?status=menunggu", fetcher, { refreshInterval: 8000 })
  const { data: conv } = useSWR<{ jumlah_per_status: Record<string, number> }>("/api/conversations", fetcher, { refreshInterval: 8000 })
  return {
    approval: ap?.items.length ?? 0,
    inbox: (conv?.jumlah_per_status?.eskalasi ?? 0) + (conv?.jumlah_per_status?.ditahan ?? 0),
  }
}

function CountBadge({ value }: { value: number }) {
  const prev = useRef(value)
  const [pulse, setPulse] = useState(0)
  useEffect(() => {
    if (value > prev.current) setPulse((p) => p + 1)
    prev.current = value
  }, [value])
  if (!value) return null
  return (
    <span
      key={pulse}
      className={cn(
        "tabular ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-gold-100 px-1.5 text-[11px] font-semibold text-escalate",
        pulse > 0 && "pulse-once",
      )}
    >
      {value}
    </span>
  )
}

function NavLinks({ role, onNavigate }: { role: Role; onNavigate?: () => void }) {
  const pathname = usePathname()
  const counts = useCounts()
  return (
    <nav className="flex flex-col gap-6" aria-label="Navigasi utama">
      {navFor(role).map((group, gi) => (
        <div key={group.label ?? gi}>
          {group.label && <div className="mb-1.5 px-3 text-[11px] font-medium tracking-[0.08em] text-subtle-foreground uppercase">{group.label}</div>}
          <ul className="flex flex-col gap-0.5">
            {group.items.map((item) => {
              const active = isActive(pathname, item.href)
              const Icon = item.icon
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex h-9 items-center gap-3 rounded-[10px] px-3 text-[13.5px] text-sidebar-foreground transition-colors hover:bg-soft",
                      active && "bg-brand-50 font-medium text-forest-900 hover:bg-brand-50",
                    )}
                  >
                    <Icon className={cn("size-[17px] shrink-0", active ? "text-brand-600" : "text-subtle-foreground")} strokeWidth={1.8} aria-hidden />
                    <span className="truncate">{item.label}</span>
                    {item.count && <CountBadge value={counts[item.count]} />}
                  </Link>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </nav>
  )
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-forest-900 font-display text-[17px] text-gold-500", className)}>
      A
    </span>
  )
}

function BudgetMeter() {
  const { data } = useSWR<Status>("/api/status", fetcher, { refreshInterval: 30000 })
  const spent = data?.anggaran.terpakai_hari_ini_rp ?? 0
  const cap = data?.anggaran.harian_rp ?? 1
  const pct = Math.min(100, (spent / cap) * 100)
  return (
    <div className="px-3">
      <div className="flex items-center justify-between text-[12px]">
        <span className="text-muted-foreground">Budget AI hari ini</span>
        <span className="tabular font-medium">{Math.round(pct)}%</span>
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-soft">
        <div className={cn("h-full rounded-full", pct >= 90 ? "bg-gold-500" : "bg-brand-500")} style={{ width: `${Math.max(2, pct)}%` }} />
      </div>
      <div className="tabular mt-1.5 text-[11.5px] text-subtle-foreground">
        {formatRp(spent, { decimals: true })} dari {formatRp(cap)}
      </div>
    </div>
  )
}

function SidebarBody({ role, onNavigate }: { role: Role; onNavigate?: () => void }) {
  return (
    <>
      <div className="flex h-16 shrink-0 items-center gap-2.5 px-5">
        <Link href="/" onClick={onNavigate} className="flex items-center gap-2.5">
          <Logo />
          <span className="leading-tight">
            <span className="block font-display text-[17px] text-forest-900">AAGE</span>
            <span className="block text-[11px] text-subtle-foreground">CV Arba&apos;in Jaya Mandiri</span>
          </span>
        </Link>
      </div>
      <div className="scrollbar-thin flex-1 overflow-y-auto px-3 py-4">
        <NavLinks role={role} onNavigate={onNavigate} />
      </div>
      <div className="space-y-4 border-t border-line py-4">
        <BudgetMeter />
        <Link
          href="/chat"
          target="_blank"
          className="mx-3 flex h-9 items-center gap-2.5 rounded-[10px] px-3 text-[13px] text-muted-foreground hover:bg-soft hover:text-foreground"
        >
          <MessageCircle className="size-4" aria-hidden /> Simulator WhatsApp
        </Link>
      </div>
    </>
  )
}

function UserMenu() {
  const router = useRouter()
  const { user, actual, role } = useRole()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false)
    window.addEventListener("mousedown", close)
    return () => window.removeEventListener("mousedown", close)
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex items-center gap-2.5 rounded-[10px] py-1 pr-2 pl-1 hover:bg-soft" aria-label="Menu akun" aria-expanded={open}>
        <span className="flex size-8 items-center justify-center rounded-full bg-brand-100 text-[13px] font-semibold text-forest-900">{user?.nama?.slice(0, 1) ?? "?"}</span>
        <span className="hidden text-left leading-tight sm:block">
          <span className="block text-[13px] font-medium">{user?.nama}</span>
          <span className="block text-[11.5px] text-subtle-foreground">{ROLE_LABEL[actual]}</span>
        </span>
      </button>
      {open && (
        <div className="glass absolute top-12 right-0 z-40 w-64 p-1.5 text-[13px]">
          <div className="px-2.5 py-2">
            <div className="font-medium">{user?.nama}</div>
            <div className="text-[12px] text-muted-foreground">{user?.email}</div>
          </div>
          {actual === "admin" && (
            <>
              <div className="my-1 h-px bg-line" />
              <div className="px-2.5 pt-1.5 pb-1 text-[11px] font-medium tracking-[0.08em] text-subtle-foreground uppercase">Lihat sebagai</div>
              {(Object.keys(ROLE_LABEL) as Role[]).map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => {
                    setRolePreview(r === "admin" ? null : r)
                    setOpen(false)
                  }}
                  className="flex h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left hover:bg-soft"
                >
                  <span className="flex-1">{ROLE_LABEL[r]}</span>
                  {role === r && <Check className="size-4 text-brand-600" />}
                </button>
              ))}
            </>
          )}
          <div className="my-1 h-px bg-line" />
          <button
            type="button"
            onClick={() => {
              clearSession()
              setRolePreview(null)
              router.replace("/login")
            }}
            className="flex h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left hover:bg-soft"
          >
            <LogOut className="size-4 text-muted-foreground" /> Keluar
          </button>
        </div>
      )}
    </div>
  )
}

function Topbar({ onOpenCommand, onOpenNav }: { onOpenCommand: () => void; onOpenNav: () => void }) {
  const { data: status } = useSWR<Status>("/api/status", fetcher, { refreshInterval: 30000 })
  const counts = useCounts()
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-background/90 px-4 backdrop-blur md:px-8">
      <button type="button" onClick={onOpenNav} className="flex size-9 items-center justify-center rounded-[10px] border border-line bg-card lg:hidden" aria-label="Buka navigasi">
        <Menu className="size-4" />
      </button>
      <button
        type="button"
        onClick={onOpenCommand}
        className="flex h-9 w-full max-w-[320px] items-center gap-2.5 rounded-[10px] border border-line bg-card px-3 text-[13px] text-subtle-foreground transition-colors hover:border-input"
      >
        <Search className="size-4" aria-hidden />
        <span className="truncate">Cari layar…</span>
        <kbd className="ml-auto hidden rounded-md border border-line px-1.5 font-mono text-[11px] text-subtle-foreground sm:inline">Ctrl K</kbd>
      </button>

      <div className="ml-auto flex items-center gap-1.5">
        <span
          className="hidden h-8 items-center gap-1.5 rounded-full border border-line bg-card px-3 text-[12px] text-muted-foreground md:inline-flex"
          title={status?.whatsapp.aktif ? "WhatsApp Business terhubung" : "Belum terhubung ke WhatsApp — memakai simulator"}
        >
          <span className={cn("size-1.5 rounded-full", status?.whatsapp.aktif ? "bg-brand-500" : "bg-gold-500")} aria-hidden />
          {status?.whatsapp.aktif ? "WhatsApp aktif" : "WhatsApp: simulator"}
        </span>
        <Link href="/approval" className="relative flex size-9 items-center justify-center rounded-[10px] text-muted-foreground hover:bg-soft" aria-label="Approval menunggu">
          <Bell className="size-[18px]" />
          {counts.approval > 0 && <span className="absolute top-2 right-2 size-2 rounded-full bg-gold-500 ring-2 ring-background" />}
        </Link>
        <span className="mx-1.5 hidden h-6 w-px bg-line sm:block" aria-hidden />
        <UserMenu />
      </div>
    </header>
  )
}

function CommandPalette({ open, onOpenChange, role }: { open: boolean; onOpenChange: (v: boolean) => void; role: Role }) {
  const router = useRouter()
  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Cari layar" description="Pindah ke layar lain">
      <CommandInput placeholder="Ketik nama layar…" />
      <CommandList>
        <CommandEmpty>Tidak ditemukan.</CommandEmpty>
        {navFor(role).map((g, gi) => (
          <CommandGroup key={g.label ?? gi} heading={g.label ?? "Umum"}>
            {g.items.map((n) => (
              <CommandItem
                key={n.href}
                onSelect={() => {
                  onOpenChange(false)
                  router.push(n.href)
                }}
              >
                <n.icon className="size-4" /> {n.label}
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  )
}

function PreviewBanner({ role }: { role: Role }) {
  return (
    <div className="flex items-center justify-center gap-2 bg-gold-100 px-4 py-1.5 text-[12.5px] text-escalate">
      <Eye className="size-3.5" aria-hidden />
      Pratinjau menu sebagai <b className="font-semibold">{ROLE_LABEL[role]}</b> — hak akses di API tidak berubah.
      <button type="button" onClick={() => setRolePreview(null)} className="ml-1 font-semibold underline underline-offset-2">
        Kembali ke Admin
      </button>
    </div>
  )
}

function Restricted({ role }: { role: Role }) {
  const pathname = usePathname()
  const label = ALL_ITEMS.find((i) => isActive(pathname, i.href))?.label ?? "Layar ini"
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-center">
      <span className="flex size-12 items-center justify-center rounded-2xl bg-soft text-muted-foreground">
        <Lock className="size-5" />
      </span>
      <h1 className="text-[22px]">Akses dibatasi</h1>
      <p className="max-w-sm text-[13.5px] text-muted-foreground">
        {label} tidak tersedia untuk role {ROLE_LABEL[role]}. Hubungi admin bila Anda memerlukan akses.
      </p>
      <Link href="/" className="btn-glass mt-2 inline-flex h-9 items-center rounded-[10px] px-4 text-[13px] font-medium">
        Ke Ringkasan
      </Link>
    </div>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const { role, previewing } = useRole()
  const [ready, setReady] = useState(false)
  const [cmd, setCmd] = useState(false)
  const [nav, setNav] = useState(false)

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login")
      return
    }
    setReady(true)
  }, [router])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault()
        setCmd((v) => !v)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [])

  if (!ready) return <div className="min-h-dvh bg-background" />

  return (
    <div className="flex min-h-dvh bg-background">
      <aside className="sticky top-0 hidden h-dvh w-[240px] shrink-0 flex-col border-r border-sidebar-border bg-sidebar lg:flex">
        <SidebarBody role={role} />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {previewing && <PreviewBanner role={role} />}
        <Topbar onOpenCommand={() => setCmd(true)} onOpenNav={() => setNav(true)} />
        <main className="mx-auto w-full max-w-[1360px] flex-1 px-4 pt-8 pb-14 md:px-8">
          {canAccess(role, pathname) ? children : <Restricted role={role} />}
        </main>
      </div>
      <CommandPalette open={cmd} onOpenChange={setCmd} role={role} />
      <Sheet open={nav} onOpenChange={setNav}>
        <SheetContent side="left" className="flex w-[260px] flex-col gap-0 bg-sidebar p-0" showCloseButton={false}>
          <SheetTitle className="sr-only">Navigasi</SheetTitle>
          <SidebarBody role={role} onNavigate={() => setNav(false)} />
        </SheetContent>
      </Sheet>
    </div>
  )
}
