"use client"

import { Bot, LoaderCircle, MessageCircle, ScrollText, ShieldCheck } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { motion } from "motion/react"
import { useState } from "react"

import { AButton } from "@/components/aage/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, saveSession, type SessionUser } from "@/lib/api"

const HIGHLIGHTS = [
  { icon: Bot, title: "Jawab pembeli 24 jam", text: "Katalog, izin edar, harga grosir, dan pesan ulang lewat WhatsApp." },
  { icon: ShieldCheck, title: "ClaimGuard", text: "Setiap kalimat diperiksa — klaim terapi tidak pernah terkirim." },
  { icon: ScrollText, title: "Ledger yang bisa diaudit", text: "Sumber, model, biaya, dan persetujuan tercatat permanen." },
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
      router.replace("/")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login gagal")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="grid min-h-dvh bg-white lg:grid-cols-2">
      <section className="brand-gradient relative m-3 hidden flex-col justify-between overflow-hidden rounded-[22px] p-10 lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="glass-on-dark flex size-9 items-center justify-center rounded-[10px] text-[15px] font-bold">A</span>
          <span className="text-[17px] font-bold tracking-tight">AAGE</span>
        </div>

        <div className="max-w-md">
          <h1 className="text-[34px] leading-[42px] font-semibold tracking-tight">Penjualan yang tumbuh, klaim yang tetap jujur.</h1>
          <p className="mt-3 text-[15px] leading-6 text-white/75">
            Agen penjualan &amp; pemasaran AI untuk CV Arba&apos;in — dari chat WhatsApp sampai konten SEO.
          </p>
          <ul className="mt-8 space-y-3">
            {HIGHLIGHTS.map((h, i) => (
              <motion.li
                key={h.title}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.1 + i * 0.06, ease: [0.22, 1, 0.36, 1] }}
                className="glass-on-dark flex items-start gap-3 rounded-[14px] p-4"
              >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/15">
                  <h.icon className="size-4" aria-hidden />
                </span>
                <span>
                  <span className="block text-[14px] font-semibold">{h.title}</span>
                  <span className="block text-[13px] text-white/70">{h.text}</span>
                </span>
              </motion.li>
            ))}
          </ul>
        </div>

        <p className="text-[12px] text-white/55">UMS Health Innovation Hackathon 2026 · ARB-01</p>
      </section>

      <section className="flex items-center justify-center p-6">
        <motion.form
          onSubmit={submit}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
          className="w-full max-w-[380px] space-y-6"
        >
          <div>
            <div className="mb-6 flex items-center gap-2.5 lg:hidden">
              <span className="flex size-9 items-center justify-center rounded-[10px] bg-[linear-gradient(145deg,var(--blue-500),var(--navy-900))] text-[15px] font-bold text-white">A</span>
              <span className="text-[17px] font-bold text-navy-900">AAGE</span>
            </div>
            <h2 className="text-[24px] leading-8 font-semibold tracking-tight">Masuk ke dashboard</h2>
            <p className="mt-1 text-muted-foreground">Untuk staf sales, marketing, dan manajemen.</p>
          </div>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className="h-11 rounded-[10px] bg-white" placeholder="nama@arbain.co.id" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Kata sandi</Label>
              <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="h-11 rounded-[10px] bg-white" />
            </div>
            {error && (
              <p role="alert" className="rounded-[10px] bg-blocked-bg px-3 py-2 text-[13px] text-blocked">
                {error}
              </p>
            )}
          </div>
          <AButton type="submit" size="lg" className="w-full" disabled={loading}>
            {loading && <LoaderCircle className="size-4 animate-spin" />} Masuk
          </AButton>
          <div className="flex items-center gap-3 text-[12px] text-subtle-foreground">
            <span className="h-px flex-1 bg-line" /> atau <span className="h-px flex-1 bg-line" />
          </div>
          <Link href="/chat" className="btn-glass flex h-11 w-full items-center justify-center gap-2 rounded-[10px] text-[14.5px] font-medium">
            <MessageCircle className="size-4" /> Coba web chat pembeli
          </Link>
          <p className="text-center text-[12px] text-subtle-foreground">Akun demo tercantum di README (data seed).</p>
        </motion.form>
      </section>
    </div>
  )
}
