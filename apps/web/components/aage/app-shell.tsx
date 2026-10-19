"use client"

import {
  BookOpen,
  ClipboardCheck,
  Inbox,
  LayoutDashboard,
  LogOut,
  MapPinned,
  Menu,
  MessageCircle,
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

type NavItem = { href: string; label: string; icon: LucideIcon; count?: "inbox" | "approval" }

export const NAV: NavItem[] = [
  { href: "/", label: "Ringkasan", icon: LayoutDashboard },
  { href: "/inbox", label: "Inbox", icon: Inbox, count: "inbox" },
  { href: "/approval", label: "Approval", icon: ClipboardCheck, count: "approval" },
  { href: "/ledger", label: "Ledger", icon: ScrollText },
  { href: "/konten", label: "Konten", icon: PenLine },
  { href: "/prospek", label: "Prospek", icon: MapPinned },
  { href: "/claimguard", label: "ClaimGuard", icon: ShieldHalf },
  { href: "/katalog", label: "Katalog", icon: BookOpen },
]

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
        "ml-auto inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-mint-glow/90 px-1.5 text-[11px] font-semibold text-emerald-950",
        pulse > 0 && "pulse-once",
      )}
    >
      {value}
    </span>
  )
}

function NavLinks({ collapsedBelowXl = true, onNavigate }: { collapsedBelowXl?: boolean; onNavigate?: () => void }) {
  const pathname = usePathname()
  const counts = useCounts()
  return (
    <nav className="flex flex-col gap-1" aria-label="Navigasi utama">
      {NAV.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)
        const Icon = item.icon
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            title={item.label}
            className={cn(
              "relative flex h-10 items-center gap-3 rounded-md px-3 text-[14px] text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-white",
              active && "bg-mint-glow/12 font-semibold text-white before:absolute before:top-2 before:bottom-2 before:left-0 before:w-0.5 before:rounded-full before:bg-mint-glow",
              collapsedBelowXl && "max-xl:justify-center max-xl:px-0",
            )}
          >
            <Icon className="size-5 shrink-0" strokeWidth={1.75} aria-hidden />
            <span className={cn(collapsedBelowXl && "max-xl:sr-only")}>{item.label}</span>
            {item.count && (
              <span className={cn("ml-auto", collapsedBelowXl && "max-xl:absolute max-xl:-top-0.5 max-xl:right-1")}>
                <CountBadge value={counts[item.count]} />
              </span>
            )}
          </Link>
        )
      })}
    </nav>
  )
}

function CostCard({ collapsedBelowXl = true }: { collapsedBelowXl?: boolean }) {
  const { data } = useSWR<Status>("/api/status", fetcher, { refreshInterval: 30000 })
  const spent = data?.anggaran.terpakai_bulan_ini_rp ?? 0
  const cap = data?.anggaran.bulanan_rp ?? 1
  return (
    <div className={cn("glass-dark !rounded-lg p-3", collapsedBelowXl && "max-xl:hidden")}>
      <div className="text-[11px] tracking-[0.02em] text-sidebar-foreground/70">Biaya AI bulan ini</div>
      <div className="tabular mt-0.5 text-lg font-semibold text-white">{formatRp(spent, { decimals: true })}</div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
        <div className="h-full rounded-full bg-mint-glow" style={{ width: `${Math.min(100, (spent / cap) * 100)}%` }} />
      </div>
      <div className="mt-1 text-[11px] text-sidebar-foreground/60">
        dari batas {formatRp(cap)} · {data?.llm.aktif ? data.llm.model.replace("gemini/", "") : "mode offline"}
      </div>
    </div>
  )
}

function Brand({ collapsedBelowXl = true }: { collapsedBelowXl?: boolean }) {
  return (
    <Link href="/" className={cn("flex items-center gap-2.5 px-2", collapsedBelowXl && "max-xl:justify-center max-xl:px-0")}>
      <span className="relative flex size-9 shrink-0 items-center justify-center rounded-xl bg-[radial-gradient(circle_at_30%_25%,var(--mint-glow),var(--emerald-500)_55%,var(--emerald-900))] shadow-[0_0_24px_-4px_rgb(167_243_208/0.6)]">
        <span className="font-display text-[17px] text-emerald-950 italic">a</span>
      </span>
      <span className={cn("leading-tight", collapsedBelowXl && "max-xl:sr-only")}>
        <span className="block font-display text-[19px] text-white">AAGE</span>
        <span className="block text-[11px] text-sidebar-foreground/60">CV Arba&apos;in · Growth Engine</span>
      </span>
    </Link>
  )
}

function Sidebar() {
  return (
    <aside className="dark-anchor sticky top-0 hidden h-dvh w-[72px] shrink-0 flex-col gap-6 border-r border-sidebar-border px-3 py-5 lg:flex xl:w-[248px] xl:px-4">
      <Brand />
      <NavLinks />
      <div className="mt-auto">
        <CostCard />
      </div>
    </aside>
  )
}

function Topbar({ user, onOpenCommand, onOpenNav }: { user: SessionUser | null; onOpenCommand: () => void; onOpenNav: () => void }) {
  const pathname = usePathname()
  const router = useRouter()
  const { data: status } = useSWR<Status>("/api/status", fetcher, { refreshInterval: 30000 })
  const current = NAV.find((n) => (n.href === "/" ? pathname === "/" : pathname.startsWith(n.href)))
  const [menu, setMenu] = useState(false)
  return (
    <header className="glass sticky top-3 z-30 mx-4 mt-3 flex h-14 items-center gap-3 !rounded-lg px-3 md:mx-6 md:px-4">
      <button type="button" onClick={onOpenNav} className="flex size-9 items-center justify-center rounded-md hover:bg-cream-100 lg:hidden" aria-label="Buka navigasi">
        <Menu className="size-5" />
      </button>
      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-[13px]">
        <span className="hidden text-muted-foreground sm:inline">AAGE</span>
        <span className="hidden text-subtle-foreground sm:inline">/</span>
        <span className="truncate font-semibold">{current?.label ?? "Dashboard"}</span>
      </nav>
      <button
        type="button"
        onClick={onOpenCommand}
        className="ml-auto flex h-9 w-full max-w-72 items-center gap-2 rounded-md border border-cream-200 bg-white/70 px-3 text-[13px] text-subtle-foreground hover:border-emerald-500/30"
      >
        <Search className="size-4" aria-hidden />
        <span className="truncate">Cari halaman atau aksi…</span>
        <kbd className="ml-auto hidden rounded border border-cream-200 bg-cream-100 px-1.5 font-mono text-[11px] sm:inline">⌘K</kbd>
      </button>
      <Link
        href="/chat"
        target="_blank"
        className="hidden h-9 items-center gap-2 rounded-md px-2.5 text-[12.5px] text-muted-foreground hover:bg-cream-100 md:flex"
        title={status?.whatsapp.aktif ? "WhatsApp Cloud API terhubung" : "WhatsApp belum dikonfigurasi — gunakan web chat cadangan"}
      >
        <span className={cn("size-2 rounded-full", status?.whatsapp.aktif ? "bg-emerald-500" : "bg-review")} aria-hidden />
        <span>{status?.whatsapp.aktif ? "WA aktif" : "WA: web chat"}</span>
      </Link>
      <div className="relative">
        <button
          type="button"
          onClick={() => setMenu((v) => !v)}
          className="flex size-9 items-center justify-center rounded-full bg-emerald-900 text-[13px] font-semibold text-primary-foreground"
          aria-label="Menu akun"
        >
          {user?.nama?.slice(0, 1) ?? "?"}
        </button>
        {menu && (
          <div className="glass glass-strong absolute top-11 right-0 w-56 !rounded-lg p-2 text-[13px]" onMouseLeave={() => setMenu(false)}>
            <div className="px-2 py-1.5">
              <div className="font-semibold">{user?.nama}</div>
              <div className="text-muted-foreground">
                {user?.email} · {user?.role === "admin" ? "Admin" : "Staf"}
              </div>
            </div>
            <button
              type="button"
              onClick={() => {
                clearSession()
                router.replace("/login")
              }}
              className="flex h-9 w-full items-center gap-2 rounded-md px-2 text-left hover:bg-cream-100"
            >
              <LogOut className="size-4" /> Keluar
            </button>
          </div>
        )}
      </div>
    </header>
  )
}

function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const router = useRouter()
  const go = (href: string) => {
    onOpenChange(false)
    router.push(href)
  }
  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Palet perintah" description="Cari halaman atau aksi">
      <CommandInput placeholder="Ketik nama halaman atau aksi…" />
      <CommandList>
        <CommandEmpty>Tidak ditemukan.</CommandEmpty>
        <CommandGroup heading="Halaman">
          {NAV.map((n) => (
            <CommandItem key={n.href} onSelect={() => go(n.href)}>
              <n.icon className="size-4" /> {n.label}
            </CommandItem>
          ))}
        </CommandGroup>
        <CommandGroup heading="Aksi cepat">
          <CommandItem onSelect={() => go("/approval")}>
            <ClipboardCheck className="size-4" /> Tinjau antrean approval <CommandShortcut>A</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={() => go("/claimguard")}>
            <ShieldHalf className="size-4" /> Periksa teks dengan ClaimGuard
          </CommandItem>
          <CommandItem onSelect={() => go("/prospek")}>
            <MapPinned className="size-4" /> Petakan prospek wilayah
          </CommandItem>
          <CommandItem onSelect={() => window.open("/chat", "_blank")}>
            <MessageCircle className="size-4" /> Buka web chat cadangan
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  )
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const [ready, setReady] = useState(false)
  const [user, setUser] = useState<SessionUser | null>(null)
  const [cmd, setCmd] = useState(false)
  const [nav, setNav] = useState(false)

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login")
      return
    }
    setUser(getUser())
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

  if (!ready) return <div className="app-bg min-h-dvh" />

  return (
    <div className="app-bg flex min-h-dvh">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar user={user} onOpenCommand={() => setCmd(true)} onOpenNav={() => setNav(true)} />
        <main className="mx-auto w-full max-w-[1440px] flex-1 px-4 pt-6 pb-10 md:px-6">{children}</main>
      </div>
      <CommandPalette open={cmd} onOpenChange={setCmd} />
      <Sheet open={nav} onOpenChange={setNav}>
        <SheetContent side="left" className="dark-anchor w-72 border-sidebar-border p-4" showCloseButton={false}>
          <SheetTitle className="sr-only">Navigasi</SheetTitle>
          <div className="flex h-full flex-col gap-6 py-2">
            <Brand collapsedBelowXl={false} />
            <NavLinks collapsedBelowXl={false} onNavigate={() => setNav(false)} />
            <div className="mt-auto">
              <CostCard collapsedBelowXl={false} />
            </div>
          </div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
