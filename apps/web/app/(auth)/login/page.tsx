"use client"

import { LoaderCircle, MessageCircle } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useState } from "react"

import { Logo } from "@/components/aage/app-shell"
import { AButton } from "@/components/aage/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, saveSession, type SessionUser } from "@/lib/api"
import { setRolePreview } from "@/lib/rbac"

const POINTS = [
  ["Asisten WhatsApp 24 jam", "Jawaban katalog bersumber dari Knowledge Base."],
  ["ClaimGuard", "Klaim kesehatan diperiksa sebelum terbit atau terkirim."],
  ["Evidence Ledger", "Setiap aksi tercatat dan dapat diaudit."],
]

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await api<{ token: string; user: SessionUser }>("/api/auth/login", { method: "POST", json: { email, password } })
      saveSession(res.token, res.user)
      setRolePreview(null)
      router.replace("/")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login gagal")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid min-h-dvh bg-background lg:grid-cols-[1fr_1.1fr]">
      <section className="brand-gradient relative hidden flex-col justify-between p-12 lg:flex">
        <div className="flex items-center gap-2.5">
          <Logo className="bg-white/10" />
          <span className="font-display text-[18px]">AAGE</span>
        </div>

        <div className="max-w-md">
          <h1 className="text-[40px] leading-[48px] text-white">
            Penjualan tumbuh, <span className="text-gold-500">klaim tetap jujur.</span>
          </h1>
          <p className="mt-4 text-[15px] leading-6 text-white/65">
            Asisten penjualan multi-agen untuk CV Arba&apos;in Jaya Mandiri — dari WhatsApp mitra B2B sampai konten SEO.
          </p>
          <ul className="mt-10 space-y-5">
            {POINTS.map(([t, d]) => (
              <li key={t} className="flex gap-3.5">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-gold-500" />
                <span>
                  <span className="block text-[14px] font-medium">{t}</span>
                  <span className="block text-[13px] text-white/60">{d}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-[12px] text-white/40">Arba&apos;in Autonomous Growth Engine · Purwarupa</p>
      </section>

      <section className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-[360px]">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <Logo />
            <span className="font-display text-[18px] text-forest-900">AAGE</span>
          </div>
          <h2 className="font-display text-[28px] leading-9 text-forest-900">Masuk</h2>
          <p className="mt-1.5 text-[13.5px] text-muted-foreground">Untuk tim Sales, Marketing, dan Manajemen.</p>

          <div className="mt-8 space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className="h-11 rounded-[10px] bg-card" placeholder="nama@arbain.co.id" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Kata sandi</Label>
              <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="h-11 rounded-[10px] bg-card" />
            </div>
            {error && (
              <p role="alert" className="rounded-[10px] bg-blocked-bg px-3 py-2 text-[13px] text-blocked">
                {error}
              </p>
            )}
          </div>

          <AButton type="submit" size="lg" className="mt-6 w-full" disabled={loading}>
            {loading && <LoaderCircle className="size-4 animate-spin" />} Masuk
          </AButton>

          <div className="mt-8 border-t border-line pt-6">
            <Link href="/chat" className="inline-flex items-center gap-2 text-[13px] font-medium text-brand-600 hover:underline">
              <MessageCircle className="size-4" /> Coba simulator WhatsApp pembeli
            </Link>
            <p className="mt-2 text-[12px] text-subtle-foreground">Akun demo tercantum di README (data seed).</p>
          </div>
        </form>
      </section>
    </div>
  )
}
