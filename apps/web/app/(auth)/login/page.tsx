"use client"

import { LoaderCircle, MessageCircle, ShieldCheck } from "lucide-react"
import dynamic from "next/dynamic"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { motion } from "motion/react"
import { useState } from "react"

import { AButton } from "@/components/aage/button"
import { StaticOrb } from "@/components/three/StaticOrb"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api, saveSession, type SessionUser } from "@/lib/api"

const LiquidOrb = dynamic(() => import("@/components/three/LiquidOrb"), {
  ssr: false,
  loading: () => <StaticOrb className="w-full" />,
})

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
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <section className="dark-anchor relative hidden flex-col justify-between overflow-hidden p-12 lg:flex">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-xl bg-[radial-gradient(circle_at_30%_25%,var(--mint-glow),var(--emerald-500)_55%,var(--emerald-900))]">
            <span className="font-display text-[17px] text-emerald-950 italic">a</span>
          </span>
          <span className="font-display text-xl text-white">AAGE</span>
        </div>
        <div className="mx-auto w-full max-w-[460px]">
          <LiquidOrb className="w-full" />
        </div>
        <div className="max-w-xl">
          <motion.h1
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.42, ease: [0.22, 1, 0.36, 1] }}
            className="font-display text-[40px] leading-[48px] font-medium text-white"
          >
            Penjualan yang tumbuh, <em className="text-mint-glow">klaim yang tetap jujur.</em>
          </motion.h1>
          <p className="mt-4 max-w-md text-sidebar-foreground/75">
            Agen penjualan & pemasaran AI CV Arba&apos;in — menjawab pembeli 24 jam, setiap kalimat diperiksa ClaimGuard dan
            tercatat di Ledger.
          </p>
          <div className="mt-6 flex gap-2 text-[12px] text-sidebar-foreground/70">
            <span className="glass-dark inline-flex items-center gap-1.5 !rounded-full px-3 py-1.5">
              <ShieldCheck className="size-3.5 text-mint-glow" /> 0 klaim terapi lolos
            </span>
            <span className="glass-dark inline-flex items-center gap-1.5 !rounded-full px-3 py-1.5">Plus Jakarta Sans · karya desainer Indonesia</span>
          </div>
        </div>
      </section>

      <section className="app-bg flex items-center justify-center p-6">
        <motion.form
          onSubmit={submit}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
          className="w-full max-w-sm space-y-6"
        >
          <div>
            <h2 className="font-display text-[32px] leading-10 font-medium lg:hidden">AAGE</h2>
            <h2 className="text-2xl leading-8 font-[650]">Masuk ke dashboard</h2>
            <p className="mt-1 text-muted-foreground">Untuk staf sales, marketing, dan manajemen CV Arba&apos;in.</p>
          </div>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className="h-11 bg-white" placeholder="nama@arbain.co.id" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Kata sandi</Label>
              <Input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="h-11 bg-white" />
            </div>
            {error && (
              <p role="alert" className="rounded-md bg-blocked-bg px-3 py-2 text-[13px] text-blocked">
                {error}
              </p>
            )}
          </div>
          <AButton type="submit" size="lg" className="w-full" disabled={loading}>
            {loading && <LoaderCircle className="size-4 animate-spin" />} Masuk
          </AButton>
          <p className="text-center text-[13px] text-muted-foreground">
            Akun demo ada di README (seed data). ·{" "}
            <Link href="/chat" className="inline-flex items-center gap-1 font-medium text-emerald-700 hover:underline">
              <MessageCircle className="size-3.5" /> Coba web chat pembeli
            </Link>
          </p>
        </motion.form>
      </section>
    </div>
  )
}
