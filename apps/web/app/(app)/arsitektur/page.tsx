import { ArrowRight, ArrowDown } from "lucide-react"

import { PageHeader, Panel } from "@/components/aage/panel"
import { AGENTS } from "@/lib/agents"

// Brief §6.1 — alur wajib setiap output.
const FLOW = [
  { title: "Agen", text: "Menyusun jawaban, konten, atau aksi" },
  { title: "ClaimGuard", text: "Aturan deterministik → LLM pendukung" },
  { title: "Policy / Approval", text: "Mode otonomi, budget, eskalasi" },
  { title: "Kanal", text: "WhatsApp, web, konten terbit" },
  { title: "Ledger", text: "Append-only, rantai hash" },
]

// Brief §7.
const STACK = [
  { layer: "Frontend", value: "Next.js + Tailwind" },
  { layer: "Backend", value: "FastAPI (modular monolith)" },
  { layer: "Data", value: "Postgres + pgvector (Supabase)" },
  { layer: "Orkestrasi", value: "LangGraph atau n8n — diputuskan Des 2026" },
  { layer: "Real-time", value: "SSE · antrean Redis" },
  { layer: "AI Gateway", value: "Model routing, caching, budget cap" },
  { layer: "Kanal", value: "WhatsApp Business Platform (sandbox dulu)" },
]

const TABLES = [
  "agents", "tasks", "products", "approved_claims", "forbidden_patterns", "knowledge_chunks", "leads", "conversations",
  "messages", "contents", "claim_checks", "approvals", "ledger", "settings", "cost_log", "users",
]

const ENDPOINTS = ["overview/*", "agents/* + SSE", "claims/check", "ledger/* (verify, export.pdf)", "leads/*", "approvals/*", "settings/*", "system/*", "webhooks/whatsapp"]

export default function ArsitekturPage() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="Arsitektur"
        description="Sistem multi-agen terkendali (controlled autonomy). Agen bekerja otomatis hanya dalam batas kebijakan; Postgres menjadi satu sumber kebenaran."
      />

      <Panel className="p-6">
        <h2 className="text-[14px] font-semibold">Alur setiap output</h2>
        <p className="mt-0.5 text-[13px] text-muted-foreground">Setiap pesan dan konten wajib melewati kelima langkah ini.</p>
        <ol className="mt-6 flex flex-col items-stretch gap-2 lg:flex-row lg:items-center">
          {FLOW.map((s, i) => (
            <li key={s.title} className="contents">
              <div
                className={
                  i === 1
                    ? "flex-1 rounded-2xl bg-forest-900 p-4 text-white"
                    : i === FLOW.length - 1
                      ? "flex-1 rounded-2xl border border-gold-500/40 bg-gold-100/60 p-4"
                      : "flex-1 rounded-2xl border border-line bg-canvas p-4"
                }
              >
                <div className="tabular text-[11px] opacity-60">0{i + 1}</div>
                <div className="mt-1 font-display text-[17px]">{s.title}</div>
                <div className={i === 1 ? "mt-1 text-[12.5px] text-white/70" : "mt-1 text-[12.5px] text-muted-foreground"}>{s.text}</div>
              </div>
              {i < FLOW.length - 1 && (
                <span className="flex justify-center text-subtle-foreground" aria-hidden>
                  <ArrowRight className="hidden size-4 lg:block" />
                  <ArrowDown className="size-4 lg:hidden" />
                </span>
              )}
            </li>
          ))}
        </ol>
      </Panel>

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Panel className="overflow-hidden">
          <div className="p-5 pb-3">
            <h2 className="text-[14px] font-semibold">Enam agen</h2>
          </div>
          <ul className="divide-y divide-line border-t border-line">
            {AGENTS.map((a, i) => (
              <li key={a.id} className="flex gap-4 px-5 py-3.5">
                <span className="tabular w-5 shrink-0 pt-0.5 text-[12px] text-subtle-foreground">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium">{a.nama}</div>
                  <div className="text-[13px] text-muted-foreground">{a.fungsi}</div>
                </div>
                <span className="h-6 shrink-0 rounded-full bg-soft px-2.5 text-[11.5px] leading-6 font-medium text-muted-foreground">{a.prioritas}</span>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel className="overflow-hidden">
          <div className="p-5 pb-3">
            <h2 className="text-[14px] font-semibold">Stack</h2>
            <p className="text-[12.5px] text-muted-foreground">Usulan — boleh diubah dengan alasan.</p>
          </div>
          <dl className="divide-y divide-line border-t border-line">
            {STACK.map((s) => (
              <div key={s.layer} className="flex gap-4 px-5 py-3 text-[13px]">
                <dt className="w-24 shrink-0 text-muted-foreground">{s.layer}</dt>
                <dd className="font-medium">{s.value}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <Panel className="p-5 lg:col-span-2">
          <h2 className="text-[14px] font-semibold">Tabel inti</h2>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {TABLES.map((t) => (
              <code key={t} className="rounded-md border border-line bg-canvas px-2 py-0.5 font-mono text-[12px]">
                {t}
              </code>
            ))}
          </div>
          <h2 className="mt-6 text-[14px] font-semibold">
            Endpoint inti <code className="font-mono text-[12px] font-normal text-muted-foreground">/api/v1</code>
          </h2>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {ENDPOINTS.map((e) => (
              <code key={e} className="rounded-md bg-brand-50 px-2 py-0.5 font-mono text-[12px] text-forest-800">
                {e}
              </code>
            ))}
          </div>
        </Panel>
        <Panel className="p-5">
          <h2 className="text-[14px] font-semibold">Rantai hash Ledger</h2>
          <p className="mt-1 text-[13px] text-muted-foreground">Setiap aksi berdampak menulis baris Ledger dalam transaksi yang sama.</p>
          <div className="mt-4 space-y-2 font-mono text-[12px]">
            {["#1041", "#1042", "#1043"].map((id, i) => (
              <div key={id} className="flex items-center gap-2 rounded-lg border border-line bg-canvas px-3 py-2">
                <span className="text-subtle-foreground">{id}</span>
                <span className="truncate">{i === 0 ? "prev_hash …a91f" : "prev_hash = hash(" + ["", "#1041", "#1042"][i] + ")"}</span>
              </div>
            ))}
          </div>
          <p className="mt-3 font-mono text-[12px] text-brand-600">sha256(prev_hash + payload)</p>
        </Panel>
      </div>
    </div>
  )
}
