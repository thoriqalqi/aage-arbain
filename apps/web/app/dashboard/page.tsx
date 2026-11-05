"use client"

// AAGE Command Center — "Virtual AI Agent Office" (tema gelap obsidian + hijau neon herbal #10b981).
// Halaman mandiri di luar shell dashboard utama. Canvas 3D dimuat dinamis (ssr:false) → aman dari error hydration.

import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCheck,
  Cpu,
  FileWarning,
  LoaderCircle,
  Play,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
  Wand2,
} from "lucide-react"
import dynamic from "next/dynamic"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { motion } from "motion/react"
import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import type { Activity, AgentId } from "@/components/command-center/OfficeScene"
import { ApiError, api, fetcher, getToken } from "@/lib/api"
import { cn } from "@/lib/utils"

const OfficeScene = dynamic(() => import("@/components/command-center/OfficeScene"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center font-mono text-xs text-emerald-400/70">
      <LoaderCircle className="mr-2 size-4 animate-spin" /> Merender kantor 3D…
    </div>
  ),
})

// ----------------------------------------------------------------- tipe dari backend (src/agents_crew.py)

type AgentEvent = {
  agent: AgentId | "orchestrator"
  message: string
  level: "info" | "progress" | "success" | "warning" | "alert" | "hitl" | "done"
  status: string | null
  data: Record<string, unknown>
  clock: string
  seq: number
}
type Pasal = { kode: string; rujukan: string; ringkasan: string }
type Audit = {
  status: "BLOCKED" | "REVIEW" | "PASSED"
  peraturan: string
  pelanggaran: { kalimat: string; status: string; temuan: { aturan: string; label: string; cocok: string; pasal: Pasal[] }[] }[]
  pasal_dilanggar: Pasal[]
  teks_terpotong: string
  notifikasi_dashboard: string | null
}
type Negosiasi = {
  status: "AUTO_APPROVED" | "NEED_HUMAN_CONFIRMATION"
  alasan: string
  laporan_staf?: string
  qty_box: number
  qty_botol: number
  subtotal: number
  diskon_tier_persen: number
  batas_diskon_maksimal_ai_persen: number
  diskon_diminta_persen: number | null
  penawaran: { diskon_persen: number; harga_per_botol: number; harga_per_box: number; total: number; margin_apotek_vs_het_persen: number }
  produk: { id: string; nama_produk: string; nomor_izin_edar_bpom: string; het_per_botol: number; harga_b2b_per_botol: number; isi_per_box: number }
}
type AgentsInfo = { model: string; mode: string; produk: number; regulasi: { judul: string; sumber: string } }

const AGENT_NAME: Record<string, string> = {
  orchestrator: "ORCHESTRATOR",
  b2b_sales_agent: "SALES",
  lead_miner_agent: "LEAD MINER",
  geo_content_agent: "GEO",
  claim_guard_agent: "CLAIMGUARD",
}
const LEVEL_CLS: Record<string, string> = {
  info: "text-zinc-300",
  progress: "text-emerald-300/90",
  success: "text-emerald-400",
  warning: "text-amber-300",
  alert: "text-rose-400",
  hitl: "text-fuchsia-300",
  done: "text-cyan-300",
}

const PROMO_MELANGGAR =
  "Madu Stamina Plus terbukti ampuh menyembuhkan diabetes dan darah tinggi hanya dalam 7 hari. " +
  "Sebanyak 95% pengguna merasakan stamina 3 kali lipat dalam sehari. " +
  "100% alami tanpa efek samping, jadi obat kuat pria paling mujarab. " +
  "Membantu memelihara stamina dan kebugaran tubuh."

const rp = (v: number) => "Rp " + Math.round(v).toLocaleString("id-ID")
const glass = "rounded-2xl border border-zinc-800 bg-zinc-900/70 backdrop-blur-lg shadow-[0_0_0_1px_rgba(16,185,129,0.04),0_20px_60px_-20px_rgba(0,0,0,0.8)]"

function PanelTitle({ icon, title, aside }: { icon: React.ReactNode; title: string; aside?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2.5 border-b border-zinc-800/80 px-5 py-3.5">
      <span className="flex size-7 items-center justify-center rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 [&_svg]:size-4">{icon}</span>
      <h2 className="text-[13.5px] font-semibold tracking-wide text-zinc-100">{title}</h2>
      <div className="ml-auto">{aside}</div>
    </div>
  )
}

// ----------------------------------------------------------------- 2. Terminal log

function useWorkdayStream(onEvent: (ev: AgentEvent) => void) {
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abort = useRef<AbortController | null>(null)

  const start = useCallback(async () => {
    setError(null)
    setRunning(true)
    const ctrl = new AbortController()
    abort.current = ctrl
    try {
      const res = await fetch("/api/agents/workday/stream?speed=1&wilayah=Kota%20Semarang", {
        headers: { Authorization: `Bearer ${getToken() ?? ""}` },
        signal: ctrl.signal,
      })
      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Stream gagal (${res.status})`)
      }
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ""
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const parts = buf.split("\n\n")
        buf = parts.pop() ?? ""
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "))
          if (!line || line === "data: {}") continue
          try {
            onEvent(JSON.parse(line.slice(6)))
          } catch {
            /* abaikan potongan rusak */
          }
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message)
    } finally {
      setRunning(false)
    }
  }, [onEvent])

  const stop = () => abort.current?.abort()
  return { start, stop, running, error }
}

function Terminal({ logs, running, error, onStart, onStop }: { logs: AgentEvent[]; running: boolean; error: string | null; onStart: () => void; onStop: () => void }) {
  const bottom = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" })
  }, [logs.length])
  return (
    <section className={cn(glass, "flex h-[560px] flex-col overflow-hidden")}>
      <PanelTitle icon={<Cpu />} title="Cyber Office Operations · Live Log"
        aside={<span className={cn("flex items-center gap-1.5 font-mono text-[11px]", running ? "text-emerald-400" : "text-zinc-500")}>
          <span className={cn("size-1.5 rounded-full", running ? "animate-pulse bg-emerald-400" : "bg-zinc-600")} />{running ? "LIVE" : "IDLE"}</span>} />
      <div className="p-4">
        {running ? (
          <button onClick={onStop} className="flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-zinc-700 bg-zinc-800/80 font-semibold text-zinc-200 hover:bg-zinc-800">
            <Square className="size-4" /> Hentikan stream
          </button>
        ) : (
          <button
            onClick={onStart}
            className="group relative flex h-12 w-full items-center justify-center gap-2 overflow-hidden rounded-xl border border-emerald-400/50 bg-[linear-gradient(180deg,#10b981,#047857)] font-semibold text-white shadow-[0_0_24px_-2px_rgba(16,185,129,0.65),inset_0_1px_0_rgba(255,255,255,0.35)] transition hover:shadow-[0_0_38px_0_rgba(16,185,129,0.85),inset_0_1px_0_rgba(255,255,255,0.35)]"
          >
            <span className="absolute inset-x-0 top-0 h-1/2 bg-white/15" />
            <span className="absolute -left-1/3 h-full w-1/3 skew-x-[-20deg] bg-white/30 opacity-0 transition-all duration-700 group-hover:left-[120%] group-hover:opacity-100" />
            <Play className="relative size-4" /> <span className="relative">Activate 3D Autonomous AI Workday</span>
          </button>
        )}
        {error && <p className="mt-2 rounded-md border border-rose-500/40 bg-rose-950/50 px-3 py-2 font-mono text-[11.5px] text-rose-300">{error}</p>}
      </div>
      <div className="scrollbar-thin mx-4 mb-4 min-h-0 flex-1 overflow-y-auto rounded-xl border border-zinc-800 bg-black/60 p-3 font-mono text-[11.5px] leading-[19px]">
        {logs.length === 0 ? (
          <p className="text-zinc-500">
            $ aage crew status<br />4 agen siaga · tekan tombol untuk memulai hari kerja otonom<span className="animate-pulse">▍</span>
          </p>
        ) : (
          logs.map((l) => (
            <div key={l.seq} className={cn("whitespace-pre-wrap", LEVEL_CLS[l.level])}>
              <span className="text-zinc-500">[{l.clock}]</span>{" "}
              <span className="font-semibold">{AGENT_NAME[l.agent] ?? l.agent}</span> {l.message}
              {l.status && l.status !== "PASSED" && <span className="ml-1 rounded bg-white/10 px-1 text-[10px]">{l.status}</span>}
            </div>
          ))
        )}
        <div ref={bottom} />
      </div>
    </section>
  )
}

// ----------------------------------------------------------------- 3. HITL & ClaimGuard

function highlight(text: string, audit: Audit | null) {
  if (!audit) return text
  const bad = audit.pelanggaran.map((v) => v.kalimat)
  const parts: React.ReactNode[] = []
  let rest = text
  bad.forEach((b, i) => {
    const idx = rest.indexOf(b)
    if (idx < 0) return
    parts.push(rest.slice(0, idx))
    const blocked = audit.pelanggaran[i].status === "BLOCKED"
    parts.push(
      <mark key={i} className={cn("rounded px-0.5 text-inherit", blocked ? "bg-rose-500/25 underline decoration-rose-500 decoration-wavy underline-offset-4" : "bg-amber-400/20")}>
        {b}
      </mark>,
    )
    rest = rest.slice(idx + b.length)
  })
  parts.push(rest)
  return parts
}

function InterventionDesk({ external }: { external: Audit | null }) {
  const [text, setText] = useState(PROMO_MELANGGAR)
  const [audit, setAudit] = useState<Audit | null>(null)
  const [busy, setBusy] = useState(false)
  const [fixed, setFixed] = useState(false)

  const run = useCallback(async (t: string) => {
    setBusy(true)
    try {
      setAudit(await api<Audit>("/api/agents/audit", { method: "POST", json: { teks: t, product_id: "ARB-002", sumber: "draf promosi marketing" } }))
    } finally {
      setBusy(false)
    }
  }, [])
  // Audit contoh dijalankan lewat tombol, karena hasilnya masuk Ledger permanen dan tidak boleh bertambah tiap halaman dibuka.
  useEffect(() => {
    if (external && external.status === "BLOCKED") {
      setFixed(false)
      setText(PROMO_MELANGGAR)
      setAudit(external)
    }
  }, [external])

  async function correct() {
    if (!audit) return
    // Hanya memotong kalimat yang melanggar. Izin edar dan sertifikat tidak ditulis di sini karena harus datang dari data terverifikasi.
    const corrected = audit.teks_terpotong.trim()
    if (!corrected) {
      toast.error("Semua kalimat contoh melanggar, jadi tidak ada teks yang tersisa.")
      return
    }
    setText(corrected)
    setFixed(true)
    await run(corrected)
  }

  const blocked = audit?.status === "BLOCKED"
  return (
    <section className={cn(glass, "overflow-hidden")}>
      <PanelTitle icon={<ShieldAlert />} title="Human-in-the-Loop & ClaimGuard Intervention Desk"
        aside={<span className="font-mono text-[10.5px] text-zinc-500">Perban BPOM 30/2023</span>} />
      <div className="grid gap-4 p-5 md:grid-cols-2">
        <div className="flex flex-col rounded-xl border border-zinc-800 bg-zinc-950/70 p-4">
          <div className="mb-3 flex items-center gap-2 text-[12px] text-zinc-400">
            <FileWarning className="size-4 text-amber-300" /> Teks contoh untuk uji, bukan draf sungguhan
            <span className={cn("ml-auto rounded-full px-2 py-0.5 text-[10.5px] font-bold", fixed && !blocked ? "bg-emerald-500/15 text-emerald-300" : "bg-rose-500/15 text-rose-300")}>
              {fixed && !blocked ? "TERKOREKSI" : "CONTOH"}
            </span>
          </div>
          <p className="flex-1 text-[13.5px] leading-6 text-zinc-200">{highlight(text, audit)}</p>
          <p className="mt-3 text-[11px] text-zinc-500">Kalimat bergaris merah = diblokir; kuning = perlu review.</p>
        </div>

          {!audit ? (
            <div key="awal" className="flex flex-col items-center justify-center gap-3 rounded-xl border border-zinc-800 p-5 text-center text-[12.5px] text-zinc-400">
              {busy ? (
                <LoaderCircle className="size-5 animate-spin" />
              ) : (
                <>
                  <p>Draf sungguhan ditinjau lewat Studio Konten dan Approval. Panel ini hanya menguji aturan pada teks contoh.</p>
                  <button onClick={() => run(text)} className="h-9 rounded-lg border border-zinc-700 px-3 text-zinc-200 hover:bg-zinc-800">Periksa teks contoh</button>
                </>
              )}
            </div>
          ) : blocked ? (
            <motion.div
              key="alert"
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1, x: [0, -3, 3, 0] }}
              transition={{ duration: 0.42 }}
              className="relative overflow-hidden rounded-xl border border-rose-500/70 bg-[linear-gradient(160deg,rgba(127,29,29,0.75),rgba(24,24,27,0.9))] p-4 shadow-[0_0_40px_-6px_rgba(244,63,94,0.7)]"
            >
              <div className="absolute inset-x-0 top-0 h-0.5 animate-pulse bg-rose-500" />
              <div className="flex items-start gap-2 font-mono text-[12.5px] font-bold tracking-wide text-rose-200">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-rose-400" /> [BPOM COMPLIANCE ALERT: OVERCLAIM FLAGGED]
              </div>
              <p className="mt-1 text-[12px] text-rose-200/80">{audit?.pelanggaran.filter((v) => v.status === "BLOCKED").length} kalimat diblokir · status BLOCKED</p>
              <ul className="mt-3 max-h-36 space-y-1.5 overflow-y-auto pr-1 text-[12px]">
                {audit?.pasal_dilanggar.map((p) => (
                  <li key={p.kode} className="rounded-md border border-rose-500/30 bg-black/30 px-2.5 py-1.5">
                    <span className="font-semibold text-rose-200">{p.rujukan}</span>
                    <span className="block text-rose-100/70">{p.ringkasan}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-2 flex flex-wrap gap-1">
                {[...new Set(audit?.pelanggaran.flatMap((v) => v.temuan.map((t) => `${t.aturan} “${t.cocok}”`)))].slice(0, 6).map((t) => (
                  <span key={t} className="rounded bg-rose-500/20 px-1.5 py-0.5 font-mono text-[10.5px] text-rose-200">{t}</span>
                ))}
              </div>
              <button
                onClick={correct}
                disabled={busy}
                className="mt-4 flex h-10 w-full items-center justify-center gap-2 rounded-lg border border-rose-300/50 bg-rose-500 font-semibold text-white shadow-[0_0_20px_-2px_rgba(244,63,94,0.8)] hover:bg-rose-400"
              >
                {busy ? <LoaderCircle className="size-4 animate-spin" /> : <Wand2 className="size-4" />} Intervensi manusia: koreksi teks otomatis
              </button>
            </motion.div>
          ) : (
            <motion.div key="ok" initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
              className="flex flex-col justify-center rounded-xl border border-emerald-500/50 bg-emerald-950/40 p-5 shadow-[0_0_30px_-8px_rgba(16,185,129,0.6)]">
              <div className="flex items-center gap-2 font-mono text-[12.5px] font-bold text-emerald-300"><ShieldCheck className="size-4" /> KEPATUHAN BPOM: {audit?.status === "REVIEW" ? "PERLU REVIEW" : "LOLOS"}</div>
              <p className="mt-2 text-[12.5px] text-emerald-100/80">Teks contoh lolos pemeriksaan aturan. Ini bukan persetujuan terbit.</p>
              <button onClick={() => { setFixed(false); setText(PROMO_MELANGGAR); run(PROMO_MELANGGAR) }}
                className="mt-4 h-9 rounded-lg border border-zinc-700 text-[12.5px] text-zinc-300 hover:bg-zinc-800">Muat ulang draf melanggar</button>
            </motion.div>
          )}
      </div>
    </section>
  )
}

// ----------------------------------------------------------------- 4. WhatsApp negotiation

type Bubble = { from: "buyer" | "ai" | "staff" | "system"; text: string; nego?: Negosiasi; time: string }
const now = () => new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" })

function WhatsAppNegotiation({ external }: { external: Negosiasi | null }) {
  const [chat, setChat] = useState<Bubble[]>([])
  const [nego, setNego] = useState<Negosiasi | null>(null)
  const [diskon, setDiskon] = useState(0)
  const [target, setTarget] = useState("")
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState<string | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end", behavior: "smooth" })
  }, [chat.length])

  const runScenario = useCallback(async (pesan: string, produk: string, qty: number, d: number | null, pembeli: string) => {
    setBusy(true)
    setSent(null)
    setChat([{ from: "buyer", text: pesan, time: now() }])
    try {
      const r = await api<{ balasan: string; negosiasi: Negosiasi }>("/api/agents/negotiate", {
        method: "POST", json: { pesan, produk, qty_box: qty, diskon_diminta: d, pembeli },
      })
      setNego(r.negosiasi)
      setDiskon(r.negosiasi.penawaran.diskon_persen)
      setChat((c) => [...c, { from: "ai", text: r.balasan, nego: r.negosiasi, time: now() }])
    } catch (e) {
      setChat((c) => [...c, { from: "system", text: e instanceof Error ? e.message : "Gagal", time: now() }])
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    runScenario("Selamat siang, saya purchasing Toko Obat Barokah. Madu Stamina Plus ambil 30 box, bisa diskon 15%? Margin kami tipis.", "ARB-002", 30, 15, "Toko Obat Barokah")
  }, [runScenario])
  useEffect(() => {
    if (external) {
      setNego(external)
      setDiskon(external.penawaran.diskon_persen)
    }
  }, [external])

  const preview = nego ? nego.produk.harga_b2b_per_botol * (1 - diskon / 100) * nego.produk.isi_per_box * nego.qty_box : 0
  const maxDiskon = nego ? Math.max(nego.diskon_diminta_persen ?? 0, nego.diskon_tier_persen) : 0

  async function approve() {
    if (!nego) return
    setBusy(true)
    try {
      const r = await api<{ status: string; detail: string; teks: string; total: number }>("/api/agents/invoice/approve", {
        method: "POST", json: { produk: nego.produk.id, qty_box: nego.qty_box, diskon_disetujui: diskon, pembeli: "Toko Obat Barokah", target_wa: target },
      })
      setChat((c) => [...c, { from: "staff", text: r.teks, time: now() }])
      setSent(r.status === "terkirim" ? "Terkirim via Fonnte API" : r.status === "simulasi" ? `Mode simulasi — ${r.detail}` : `Gagal: ${r.detail}`)
    } catch (e) {
      setSent(e instanceof ApiError ? e.message : "Gagal mengirim")
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={cn(glass, "flex flex-col overflow-hidden")}>
      <PanelTitle icon={<Bot />} title="B2B WhatsApp Negotiation"
        aside={<div className="flex gap-1.5">
          <button onClick={() => runScenario("Propolis tetes 50 box, diskon 8% bisa ya?", "ARB-006", 50, 8, "Apotek Sehat Sentosa")}
            className="rounded-md border border-zinc-700 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-800">Nego aman 8%</button>
          <button onClick={() => runScenario("Madu Stamina Plus ambil 30 box, bisa diskon 15%?", "ARB-002", 30, 15, "Toko Obat Barokah")}
            className="rounded-md border border-zinc-700 px-2 py-1 text-[11px] text-zinc-300 hover:bg-zinc-800">Nego 15%</button>
        </div>} />
      <div className="flex items-center gap-3 border-b border-zinc-800 bg-[#202c33]/60 px-4 py-2.5">
        <span className="flex size-9 items-center justify-center rounded-full bg-emerald-700 text-[13px] font-bold text-white">TB</span>
        <div className="leading-tight">
          <div className="text-[13.5px] font-semibold text-zinc-100">Toko Obat Barokah · Purchasing</div>
          <div className="text-[11px] text-emerald-400">{busy ? "AI sedang menghitung…" : "online"}</div>
        </div>
      </div>
      <div className="scrollbar-thin cc-wa-bg h-[300px] space-y-2.5 overflow-y-auto px-4 py-4">
        {chat.map((b, i) => (
          <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className={cn("flex", b.from === "buyer" ? "justify-start" : "justify-end")}>
            <div className={cn("max-w-[88%] rounded-xl px-3 py-2 text-[12.5px] leading-5 whitespace-pre-wrap shadow",
              b.from === "buyer" && "rounded-tl-sm bg-[#202c33] text-zinc-100",
              b.from === "ai" && "rounded-tr-sm bg-[#005c4b] text-emerald-50",
              b.from === "staff" && "rounded-tr-sm border border-emerald-400/40 bg-[#063a30] font-mono text-[11.5px] text-emerald-100",
              b.from === "system" && "bg-rose-950 text-rose-200")}>
              {b.from === "ai" && <div className="mb-1 flex items-center gap-1 text-[10px] font-bold tracking-wider text-emerald-300 uppercase"><Sparkles className="size-3" /> Sales Agent AI</div>}
              {b.from === "staff" && <div className="mb-1 text-[10px] font-bold tracking-wider text-emerald-300 uppercase">Invoice disetujui staf</div>}
              {b.text}
              {b.nego && (
                <div className="mt-2 space-y-1 rounded-lg bg-black/25 p-2 font-mono text-[11px]">
                  <div className="flex justify-between"><span>Volume</span><span>{b.nego.qty_box} box · {b.nego.qty_botol} botol</span></div>
                  <div className="flex justify-between"><span>Tier volume</span><span>{b.nego.diskon_tier_persen}%</span></div>
                  <div className="flex justify-between"><span>Batas AI</span><span>{b.nego.batas_diskon_maksimal_ai_persen}%</span></div>
                  <div className="flex justify-between"><span>Diminta</span><span className={(b.nego.diskon_diminta_persen ?? 0) > b.nego.batas_diskon_maksimal_ai_persen ? "text-rose-300" : ""}>{b.nego.diskon_diminta_persen ?? "-"}%</span></div>
                  <div className="flex justify-between border-t border-white/10 pt-1"><span>Penawaran AI</span><span>{rp(b.nego.penawaran.total)}</span></div>
                  <div className="flex justify-between"><span>Margin vs HET</span><span>{b.nego.penawaran.margin_apotek_vs_het_persen}%</span></div>
                  <div className={cn("mt-1 rounded px-1.5 py-0.5 text-center font-bold", b.nego.status === "AUTO_APPROVED" ? "bg-emerald-400/20 text-emerald-200" : "bg-fuchsia-500/20 text-fuchsia-200")}>
                    {b.nego.status}
                  </div>
                </div>
              )}
              <div className="mt-1 flex items-center justify-end gap-1 text-[10px] text-zinc-400">{b.time}{b.from !== "buyer" && <CheckCheck className="size-3 text-sky-400" />}</div>
            </div>
          </motion.div>
        ))}
        {busy && <div className="w-fit rounded-xl bg-[#202c33] px-3 py-2 text-[12px] text-zinc-400">mengetik…</div>}
        <div ref={bottom} />
      </div>
      {nego && (
        <div className="space-y-3 border-t border-zinc-800 p-4">
          {nego.laporan_staf && (
            <details className="rounded-lg border border-fuchsia-500/30 bg-fuchsia-950/30 px-3 py-2 text-[11.5px] text-fuchsia-100">
              <summary className="cursor-pointer font-semibold">Draf laporan eskalasi untuk staf</summary>
              <pre className="mt-2 font-mono whitespace-pre-wrap">{nego.laporan_staf}</pre>
            </details>
          )}
          <div className="flex flex-wrap items-center gap-3 text-[12px] text-zinc-300">
            <label className="flex items-center gap-2">Diskon final staf
              <input type="range" min={0} max={maxDiskon} step={0.5} value={diskon} onChange={(e) => setDiskon(Number(e.target.value))} className="accent-emerald-500" />
              <span className="w-10 font-mono text-emerald-300">{diskon}%</span>
            </label>
            <span className="font-mono">Total {rp(preview)}</span>
            <input value={target} onChange={(e) => setTarget(e.target.value.replace(/[^\d]/g, ""))} placeholder="No. WA tujuan (62…) — opsional"
              className="ml-auto h-8 w-52 rounded-md border border-zinc-700 bg-zinc-950 px-2 font-mono text-[11.5px] text-zinc-200 placeholder:text-zinc-600" />
          </div>
          <button
            onClick={approve}
            disabled={busy}
            className="group relative flex h-11 w-full items-center justify-center gap-2 overflow-hidden rounded-xl border border-emerald-300/40 bg-[linear-gradient(135deg,#10b981,#065f46)] font-semibold text-white shadow-[0_0_26px_-4px_rgba(16,185,129,0.8),inset_0_1px_0_rgba(255,255,255,0.35)] disabled:opacity-60"
          >
            <span className="absolute inset-x-0 top-0 h-1/2 bg-white/10" />
            <span className="absolute -left-1/3 h-full w-1/3 skew-x-[-20deg] bg-white/30 opacity-0 transition-all duration-700 group-hover:left-[120%] group-hover:opacity-100" />
            <Send className="relative size-4" /> <span className="relative">Approve Invoice &amp; Kirim via Fonnte API</span>
          </button>
          {sent && <p className="text-center font-mono text-[11px] text-emerald-300/90">{sent}</p>}
        </div>
      )}
    </section>
  )
}

// ----------------------------------------------------------------- halaman

export default function CommandCenterPage() {
  const router = useRouter()
  const [ready, setReady] = useState(false)
  const [logs, setLogs] = useState<AgentEvent[]>([])
  const [activity, setActivity] = useState<Activity>({})
  const [statuses, setStatuses] = useState<Partial<Record<AgentId, string>>>({})
  const [alertAudit, setAlertAudit] = useState<Audit | null>(null)
  const [hitlNego, setHitlNego] = useState<Negosiasi | null>(null)
  const { data: info } = useSWR<AgentsInfo>(ready ? "/api/agents" : null, fetcher)

  useEffect(() => {
    if (!getToken()) router.replace("/login")
    else setReady(true)
  }, [router])

  const onEvent = useCallback((ev: AgentEvent) => {
    setLogs((l) => [...l.slice(-300), ev])
    if (ev.agent !== "orchestrator") {
      setActivity((a) => ({ ...a, [ev.agent]: performance.now() }))
      if (ev.status) setStatuses((s) => ({ ...s, [ev.agent]: ev.status! }))
    }
    if (ev.status === "BLOCKED" && ev.data.audit) setAlertAudit(ev.data.audit as Audit)
    const item = ev.data.item as { jenis?: string; negosiasi?: Negosiasi } | undefined
    if (ev.level === "hitl" && item?.jenis === "negosiasi" && item.negosiasi) setHitlNego(item.negosiasi)
  }, [])
  const { start, stop, running, error } = useWorkdayStream(onEvent)

  if (!ready) return <div className="min-h-dvh bg-[#060607]" />

  return (
    <div className="cc-bg min-h-dvh text-zinc-100">
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-zinc-800/80 bg-black/60 px-4 backdrop-blur-lg md:px-6">
        <Link href="/" className="flex size-8 items-center justify-center rounded-lg border border-zinc-800 text-zinc-400 hover:text-zinc-100" aria-label="Kembali ke dashboard"><ArrowLeft className="size-4" /></Link>
        <span className="flex size-8 items-center justify-center rounded-lg bg-[linear-gradient(145deg,#34d399,#065f46)] text-[14px] font-bold shadow-[0_0_18px_-2px_rgba(16,185,129,0.8)]">A</span>
        <div className="leading-tight">
          <div className="text-[14px] font-semibold tracking-wide">AAGE Command Center</div>
          <div className="font-mono text-[10.5px] text-zinc-500">Virtual AI Agent Office · CV Arba&apos;in</div>
        </div>
        <div className="ml-auto flex items-center gap-2 font-mono text-[11px]">
          {info && (
            <>
              <span className="hidden rounded-full border border-zinc-800 px-2.5 py-1 text-zinc-400 md:inline">{info.model.replace("anthropic/", "")}</span>
              <span className={cn("rounded-full border px-2.5 py-1", info.mode === "llm" ? "border-emerald-500/50 text-emerald-300" : "border-amber-500/40 text-amber-300")}>
                mode {info.mode}
              </span>
              <span className="hidden rounded-full border border-zinc-800 px-2.5 py-1 text-zinc-400 sm:inline">{info.produk} produk RAG</span>
            </>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] space-y-5 p-4 md:p-6">
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_440px]">
          <section className={cn(glass, "relative h-[560px] overflow-hidden")}>
            <div className="pointer-events-none absolute top-0 left-0 z-10 flex items-center gap-2 p-4">
              <span className="rounded-md border border-emerald-500/40 bg-black/60 px-2 py-1 font-mono text-[10.5px] tracking-widest text-emerald-300 uppercase">The 3D Virtual AI Office</span>
              <span className="font-mono text-[10.5px] text-zinc-500">seret · putar · scroll untuk zoom</span>
            </div>
            <OfficeScene activity={activity} statuses={statuses} />
            <div className="pointer-events-none absolute right-4 bottom-4 z-10 grid grid-cols-2 gap-1.5 font-mono text-[10.5px]">
              {(["b2b_sales_agent", "lead_miner_agent", "geo_content_agent", "claim_guard_agent"] as AgentId[]).map((id) => (
                <span key={id} className={cn("rounded-md border bg-black/60 px-2 py-1",
                  statuses[id] === "BLOCKED" ? "border-rose-500/60 text-rose-300" : activity[id] ? "border-emerald-500/40 text-emerald-300" : "border-zinc-800 text-zinc-500")}>
                  {AGENT_NAME[id]} · {statuses[id] ?? "siaga"}
                </span>
              ))}
            </div>
          </section>
          <Terminal logs={logs} running={running} error={error} onStart={() => { setLogs([]); setStatuses({}); start() }} onStop={stop} />
        </div>
        <div className="grid gap-5 xl:grid-cols-2">
          <InterventionDesk external={alertAudit} />
          <WhatsAppNegotiation external={hitlNego} />
        </div>
        <p className="pb-4 text-center font-mono text-[10.5px] text-zinc-600">
          Data produk simulasi · rujukan pasal: {info?.regulasi.judul ?? "Perban BPOM 30/2023"} (Lampiran perlu verifikasi) · keputusan harga & klaim deterministik, LLM tidak dapat menurunkan BLOCKED
        </p>
      </main>
    </div>
  )
}
