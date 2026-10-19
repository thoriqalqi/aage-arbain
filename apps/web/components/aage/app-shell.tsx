"use client"

import {
  Bell,
  Boxes,
  BookOpen,
  ChevronsUpDown,
  ClipboardCheck,
  Inbox,
  LayoutDashboard,
  LogOut,
  MapPinned,
  Menu,
  MessageCircle,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  ScrollText,
  Search,
  ShieldHalf,
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
  CommandShortcut,
} from "@/components/ui/command"
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet"
import { clearSession, fetcher, getToken, getUser, type SessionUser } from "@/lib/api"
import { formatRp } from "@/lib/format"
import type { Status } from "@/lib/types"
import { cn } from "@/lib/utils"

type NavItem = { href: string; label: string; icon: LucideIcon; count?: "inbox" | "approval"; external?: boolean }

export const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Umum",
    items: [
      { href: "/", label: "Ringkasan", icon: LayoutDashboard },
      { href: "/dashboard", label: "Command Center", icon: Boxes, external: false },
      { href: "/inbox", label: "Inbox", icon: Inbox, count: "inbox" },
      { href: "/approval", label: "Approval", icon: ClipboardCheck, count: "approval" },
      { href: "/ledger", label: "Ledger", icon: ScrollText },
    ],
  },
  {
    label: "Alat",
    items: [
      { href: "/konten", label: "Konten & GEO", icon: PenLine },
      { href: "/prospek", label: "Prospek", icon: MapPinned },
      { href: "/claimguard", label: "ClaimGuard", icon: ShieldHalf },
      { href: "/katalog", label: "Katalog", icon: BookOpen },
    ],
  },
  {
    label: "Dukungan",
    items: [{ href: "/chat", label: "Web chat demo", icon: MessageCircle, external: true }],
  },
]
export const NAV = NAV_GROUPS.flatMap((g) => g.items)

function useCounts() {
  const { data: ap } = useSWR<{ items: unknown[] }>("/api/approvals?status=menunggu", fetcher, { refreshInterval: 8000 })
  const { data: conv } = useSWR<{ jumlah_per_status: Record<string, number> }>("/api/conversations", fetcher, { refreshInterval: 8000 })
  return {
    approval: ap?.items.length ?? 0,
    inbox: (conv?.jumlah_per_status?.eskalasi ?? 0) + (conv?.jumlah_per_status?.ditahan ?? 0),
  }
}

function CountBadge({ value, collapsed }: { value: number; collapsed: boolean }) {
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
        "inline-flex h-5 min-w-5 items-center justify-center rounded-md border border-line bg-white px-1.5 text-[11px] font-semibold text-navy-900",
        collapsed && "absolute -top-1 -right-1 h-4 min-w-4 rounded-full border-0 bg-navy-900 px-1 text-[10px] text-white",
        pulse > 0 && "pulse-once",
      )}
    >
      {value}
    </span>
  )
}

function NavLinks({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname()
  const counts = useCounts()
  return (
    <nav className="flex flex-col gap-5" aria-label="Navigasi utama">
      {NAV_GROUPS.map((group) => (
        <div key={group.label}>
          {collapsed ? (
            <div className="mx-auto mb-2 h-px w-6 bg-line" aria-hidden />
          ) : (
            <div className="mb-1.5 px-3 text-[11px] font-medium tracking-[0.06em] text-subtle-foreground uppercase">{group.label}</div>
          )}
          <ul className="flex flex-col gap-0.5">
            {group.items.map((item) => {
              const active = !item.external && (item.href === "/" ? pathname === "/" : pathname.startsWith(item.href))
              const Icon = item.icon
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    target={item.external ? "_blank" : undefined}
                    onClick={onNavigate}
                    title={collapsed ? item.label : undefined}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "relative flex h-9 items-center gap-3 rounded-[10px] px-3 text-[13.5px] text-sidebar-foreground transition-colors hover:bg-soft",
                      active && "bg-blue-50 font-semibold text-navy-900 ring-1 ring-blue-100 hover:bg-blue-50",
                      collapsed && "justify-center px-0",
                    )}
                  >
                    <Icon className={cn("size-[18px] shrink-0", active ? "text-navy-900" : "text-muted-foreground")} strokeWidth={1.8} aria-hidden />
                    {!collapsed && <span className="truncate">{item.label}</span>}
                    {item.count && (
                      <span className={cn(!collapsed && "ml-auto")}>
                        <CountBadge value={counts[item.count]} collapsed={collapsed} />
                      </span>
                    )}
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

function Logo() {
  return (
    <span className="flex size-8 shrink-0 items-center justify-center rounded-[10px] bg-[linear-gradient(145deg,var(--blue-500),var(--navy-900))] text-[15px] font-bold text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.3)]">
      A
    </span>
  )
}

function WorkspaceCard({ collapsed }: { collapsed: boolean }) {
  const { data } = useSWR<Status>("/api/status", fetcher, { refreshInterval: 30000 })
  const spent = data?.anggaran.terpakai_bulan_ini_rp ?? 0
  const cap = data?.anggaran.bulanan_rp ?? 1
  if (collapsed) {
    return (
      <div className="flex justify-center" title={`Biaya AI bulan ini ${formatRp(spent, { decimals: true })}`}>
        <span className="flex size-9 items-center justify-center rounded-[10px] bg-blue-50 text-[12px] font-semibold text-navy-900">CV</span>
      </div>
    )
  }
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-line bg-soft/60 p-3">
        <div className="flex items-center justify-between text-[12px]">
          <span className="text-muted-foreground">Biaya AI bulan ini</span>
          <span className="tabular font-semibold text-foreground">{formatRp(spent, { decimals: true })}</span>
        </div>
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line">
          <div className="h-full rounded-full bg-[linear-gradient(90deg,var(--blue-400),var(--navy-900))]" style={{ width: `${Math.max(2, Math.min(100, (spent / cap) * 100))}%` }} />
        </div>
        <div className="mt-1.5 text-[11px] text-subtle-foreground">
          batas {formatRp(cap)} · {data?.llm.aktif ? data.llm.model.replace("gemini/", "") : "mode offline"}
        </div>
      </div>
      <div className="flex items-center gap-3 rounded-xl border border-line bg-white p-2.5">
        <span className="flex size-9 items-center justify-center rounded-[10px] bg-[linear-gradient(145deg,var(--blue-400),var(--navy-800))] text-[12px] font-semibold text-white">CV</span>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="text-[11px] text-subtle-foreground">Tim</div>
          <div className="truncate text-[13px] font-semibold">CV Arba&apos;in · Penjualan</div>
        </div>
        <ChevronsUpDown className="size-4 text-subtle-foreground" aria-hidden />
      </div>
    </div>
  )
}

function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200 lg:flex",
        collapsed ? "w-[76px]" : "w-[252px]",
      )}
    >
      <div className={cn("flex h-16 items-center gap-2.5 border-b border-line", collapsed ? "justify-center px-2" : "px-5")}>
        <Link href="/" className="flex items-center gap-2.5">
          <Logo />
          {!collapsed && <span className="text-[17px] font-bold tracking-tight text-navy-900">AAGE</span>}
        </Link>
        {!collapsed && (
          <button
            type="button"
            onClick={onToggle}
            className="ml-auto flex size-8 items-center justify-center rounded-lg border border-line text-muted-foreground hover:bg-soft"
            aria-label="Ciutkan sidebar"
          >
            <PanelLeftClose className="size-4" />
          </button>
        )}
      </div>
      <div className={cn("scrollbar-thin flex-1 overflow-y-auto py-5", collapsed ? "px-3" : "px-4")}>
        {collapsed && (
          <button
            type="button"
            onClick={onToggle}
            className="mx-auto mb-4 flex size-9 items-center justify-center rounded-lg border border-line text-muted-foreground hover:bg-soft"
            aria-label="Lebarkan sidebar"
          >
            <PanelLeftOpen className="size-4" />
          </button>
        )}
        <NavLinks collapsed={collapsed} />
      </div>
      <div className={cn("border-t border-line py-4", collapsed ? "px-3" : "px-4")}>
        <WorkspaceCard collapsed={collapsed} />
      </div>
    </aside>
  )
}

function Topbar({ user, onOpenCommand, onOpenNav }: { user: SessionUser | null; onOpenCommand: () => void; onOpenNav: () => void }) {
  const router = useRouter()
  const { data: status } = useSWR<Status>("/api/status", fetcher, { refreshInterval: 30000 })
  const counts = useCounts()
  const [menu, setMenu] = useState(false)
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-white/90 px-4 backdrop-blur md:px-8">
      <button type="button" onClick={onOpenNav} className="flex size-9 items-center justify-center rounded-lg border border-line lg:hidden" aria-label="Buka navigasi">
        <Menu className="size-4" />
      </button>
      <button
        type="button"
        onClick={onOpenCommand}
        className="flex h-10 w-full max-w-[360px] items-center gap-2.5 rounded-[10px] border border-line bg-white px-3 text-[13.5px] text-subtle-foreground transition-colors hover:border-blue-300"
      >
        <Search className="size-4" aria-hidden />
        <span className="truncate">Cari halaman atau aksi</span>
        <kbd className="ml-auto hidden rounded-md border border-line bg-soft px-1.5 font-mono text-[11px] text-muted-foreground sm:inline">⌘ K</kbd>
      </button>

      <div className="ml-auto flex items-center gap-1.5">
        <span
          className="hidden h-8 items-center gap-1.5 rounded-full border border-line px-3 text-[12px] text-muted-foreground md:inline-flex"
          title={status?.whatsapp.aktif ? "WhatsApp Cloud API terhubung" : "WhatsApp belum dikonfigurasi — gunakan web chat cadangan"}
        >
          <span className={cn("size-1.5 rounded-full", status?.whatsapp.aktif ? "bg-ok" : "bg-review")} aria-hidden />
          {status?.whatsapp.aktif ? "WhatsApp aktif" : "WhatsApp: web chat"}
        </span>
        <Link href="/approval" className="relative flex size-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-soft" aria-label="Approval menunggu">
          <Bell className="size-[18px]" />
          {counts.approval > 0 && <span className="absolute top-2 right-2 size-2 rounded-full bg-blue-500 ring-2 ring-white" />}
        </Link>
        <span className="mx-2 hidden h-6 w-px bg-line sm:block" aria-hidden />
        <div className="relative">
          <button type="button" onClick={() => setMenu((v) => !v)} className="flex items-center gap-2.5 rounded-lg py-1 pr-1 pl-1 hover:bg-soft" aria-label="Menu akun">
            <span className="flex size-8 items-center justify-center rounded-full bg-blue-100 text-[13px] font-semibold text-navy-900">
              {user?.nama?.slice(0, 1) ?? "?"}
            </span>
            <span className="hidden text-left leading-tight sm:block">
              <span className="block text-[13px] font-semibold">{user?.nama}</span>
              <span className="block text-[11.5px] text-subtle-foreground">{user?.role === "admin" ? "Admin" : "Staf"}</span>
            </span>
          </button>
          {menu && (
            <div className="glass glass-strong absolute top-12 right-0 w-56 p-1.5 text-[13px]" onMouseLeave={() => setMenu(false)}>
              <div className="px-2.5 py-2 text-muted-foreground">{user?.email}</div>
              <button
                type="button"
                onClick={() => {
                  clearSession()
                  router.replace("/login")
                }}
                className="flex h-9 w-full items-center gap-2 rounded-lg px-2.5 text-left hover:bg-soft"
              >
                <LogOut className="size-4" /> Keluar
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}

function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const router = useRouter()
  const go = (href: string, external?: boolean) => {
    onOpenChange(false)
    if (external) window.open(href, "_blank")
    else router.push(href)
  }
  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Palet perintah" description="Cari halaman atau aksi">
      <CommandInput placeholder="Ketik nama halaman atau aksi…" />
      <CommandList>
        <CommandEmpty>Tidak ditemukan.</CommandEmpty>
        {NAV_GROUPS.map((g) => (
          <CommandGroup key={g.label} heading={g.label}>
            {g.items.map((n) => (
              <CommandItem key={n.href} onSelect={() => go(n.href, n.external)}>
                <n.icon className="size-4" /> {n.label}
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
        <CommandGroup heading="Aksi cepat">
          <CommandItem onSelect={() => go("/approval")}>
            <ClipboardCheck className="size-4" /> Tinjau antrean approval <CommandShortcut>A</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={() => go("/prospek")}>
            <MapPinned className="size-4" /> Petakan prospek wilayah
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  )
}

const COLLAPSE_KEY = "aage.sidebar.collapsed"

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [ready, setReady] = useState(false)
  const [user, setUser] = useState<SessionUser | null>(null)
  const [cmd, setCmd] = useState(false)
  const [nav, setNav] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login")
      return
    }
    setUser(getUser())
    try {
      setCollapsed(window.localStorage.getItem(COLLAPSE_KEY) === "1")
    } catch {
      /* abaikan */
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

  const toggle = () =>
    setCollapsed((v) => {
      try {
        window.localStorage.setItem(COLLAPSE_KEY, v ? "0" : "1")
      } catch {
        /* abaikan */
      }
      return !v
    })

  if (!ready) return <div className="min-h-dvh bg-background" />

  return (
    <div className="flex min-h-dvh bg-background">
      <Sidebar collapsed={collapsed} onToggle={toggle} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar user={user} onOpenCommand={() => setCmd(true)} onOpenNav={() => setNav(true)} />
        <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 pt-7 pb-12 md:px-8">{children}</main>
      </div>
      <CommandPalette open={cmd} onOpenChange={setCmd} />
      <Sheet open={nav} onOpenChange={setNav}>
        <SheetContent side="left" className="w-72 bg-white p-0" showCloseButton={false}>
          <SheetTitle className="sr-only">Navigasi</SheetTitle>
          <div className="flex h-16 items-center gap-2.5 border-b border-line px-5">
            <Logo />
            <span className="text-[17px] font-bold tracking-tight text-navy-900">AAGE</span>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-5">
            <NavLinks collapsed={false} onNavigate={() => setNav(false)} />
          </div>
          <div className="border-t border-line p-4">
            <WorkspaceCard collapsed={false} />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
