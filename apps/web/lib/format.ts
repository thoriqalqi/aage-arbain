// Format lokal Indonesia (design.md §11–12): Rp 1.250 · 12,5% · 19 Okt 2026, 20.33

const rp = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 0 })
const num = new Intl.NumberFormat("id-ID", { maximumFractionDigits: 1 })
const BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

export function formatRp(value: number | null | undefined, opts: { decimals?: boolean } = {}): string {
  if (value == null || Number.isNaN(value)) return "—"
  if (opts.decimals && value > 0 && value < 100) {
    return "Rp " + value.toLocaleString("id-ID", { maximumFractionDigits: 2 })
  }
  return "Rp " + rp.format(value)
}

export function formatNum(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—"
  return num.format(value)
}

export function formatPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—"
  return num.format(value) + "%"
}

function toDate(v: string | Date): Date {
  return typeof v === "string" ? new Date(v) : v
}

const pad = (n: number) => String(n).padStart(2, "0")

export function formatDateTime(v: string | Date | null | undefined): string {
  if (!v) return "—"
  const d = toDate(v)
  return `${d.getDate()} ${BULAN[d.getMonth()]} ${d.getFullYear()}, ${pad(d.getHours())}.${pad(d.getMinutes())}`
}

export function formatTime(v: string | Date | null | undefined): string {
  if (!v) return "—"
  const d = toDate(v)
  return `${pad(d.getHours())}.${pad(d.getMinutes())}`
}

export function formatDay(v: string | Date): string {
  const d = toDate(v)
  return `${d.getDate()} ${BULAN[d.getMonth()]}`
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—"
  if (ms < 1000) return `${Math.round(ms)} md`
  if (ms < 60_000) return `${num.format(ms / 1000)} dtk`
  return `${num.format(ms / 60_000)} mnt`
}

export function relativeTime(v: string | Date | null | undefined): string {
  if (!v) return "—"
  const diff = (Date.now() - toDate(v).getTime()) / 1000
  if (diff < 60) return "baru saja"
  if (diff < 3600) return `${Math.floor(diff / 60)} mnt lalu`
  if (diff < 86400) return `${Math.floor(diff / 3600)} jam lalu`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} hari lalu`
  return formatDateTime(v)
}

export function contactName(c: { nama_toko: string | null; wa_number: string } | null | undefined): string {
  if (!c) return "Pembeli"
  if (c.nama_toko) return c.nama_toko
  return c.wa_number.startsWith("web:") ? `Pengunjung web chat · ${c.wa_number.slice(-4)}` : c.wa_number
}
