"use client"

import { Lock, UserRoundCheck } from "lucide-react"
import { Suspense, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { AutonomyPicker } from "@/components/aage/autonomy-picker"
import { SkeletonRows } from "@/components/aage/empty-state"
import { KatalogManager } from "@/components/aage/katalog-manager"
import { PageTabs, usePageTab } from "@/components/aage/page-tabs"
import { PageHeader, Panel } from "@/components/aage/panel"
import { Input } from "@/components/ui/input"
import { AGENTS, AUTONOMY_HINT, type AutonomyMode } from "@/lib/agents"
import { fetcher } from "@/lib/api"
import { formatRp } from "@/lib/format"
import { useRole } from "@/lib/rbac"
import type { Status } from "@/lib/types"
import { saveSettings, type AgentsStatus, type SettingsSnapshot } from "@/lib/use-agent-status"
import { cn } from "@/lib/utils"

const TABS = ["kebijakan", "otonomi", "anggaran", "katalog"] as const

// Brief §6 — aturan inti yang wajib dan tidak bisa dimatikan dari UI.
const CORE_RULES = [
  { title: "Semua output lewat ClaimGuard", text: "Alur tetap: Agen → ClaimGuard → Policy/Approval → Kanal → Ledger." },
  { title: "Aturan deterministik lebih dulu", text: "Klaim terapi, klaim berlebih, statistik tanpa sumber, dan perbandingan tanpa bukti. LLM hanya pemeriksa pendukung." },
  { title: "Jawaban otomatis harus bersumber", text: "Hanya dari Knowledge Base. Selain itu dieskalasi ke staf dengan ringkasan." },
  { title: "Ledger dalam transaksi yang sama", text: "Append-only dengan rantai hash sha256(prev_hash + payload)." },
  { title: "Hanya kontak inbound/opt-in", text: "Minimisasi data sesuai UU PDP dan kebijakan WhatsApp Business." },
  { title: "Konten SEO jujur", text: "Tanpa janji ranking dan tanpa statistik tanpa sumber." },
]

const ALWAYS_ESCALATE = ["Harga", "MOQ", "Negosiasi", "Klaim kesehatan"]

function Kebijakan() {
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
      <Panel className="divide-y divide-line">
        <div className="p-5">
          <h2 className="text-[14px] font-semibold">Aturan inti</h2>
          <p className="mt-0.5 text-[13px] text-muted-foreground">Wajib untuk semua agen. Diubah hanya lewat revisi kebijakan, bukan dari dashboard.</p>
        </div>
        {CORE_RULES.map((r, i) => (
          <div key={r.title} className="flex gap-4 px-5 py-4">
            <span className="tabular mt-0.5 w-5 shrink-0 text-[12px] text-subtle-foreground">{String(i + 1).padStart(2, "0")}</span>
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-medium">{r.title}</div>
              <div className="mt-0.5 text-[13px] text-muted-foreground">{r.text}</div>
            </div>
            <Lock className="mt-0.5 size-4 shrink-0 text-subtle-foreground" aria-label="Terkunci" />
          </div>
        ))}
      </Panel>
      <div className="space-y-5">
        <Panel className="p-5">
          <div className="flex items-center gap-2">
            <UserRoundCheck className="size-4 text-escalate" />
            <h2 className="text-[14px] font-semibold">Selalu ke manusia</h2>
          </div>
          <p className="mt-1 text-[13px] text-muted-foreground">Topik ini tidak pernah dijawab agen secara otomatis.</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {ALWAYS_ESCALATE.map((t) => (
              <span key={t} className="inline-flex h-7 items-center rounded-full bg-escalate-bg px-3 text-[12.5px] font-medium text-escalate">
                {t}
              </span>
            ))}
          </div>
        </Panel>
        <Panel className="p-5">
          <h2 className="text-[14px] font-semibold">Keputusan ClaimGuard</h2>
          <ul className="mt-3 space-y-2.5 text-[13px]">
            <li className="flex items-center gap-2.5"><span className="size-2 rounded-full bg-ok" /> <b className="font-medium">Diizinkan</b> <span className="text-muted-foreground">— boleh terkirim</span></li>
            <li className="flex items-center gap-2.5"><span className="size-2 rounded-full bg-review" /> <b className="font-medium">Perlu review</b> <span className="text-muted-foreground">— masuk antrean approval</span></li>
            <li className="flex items-center gap-2.5"><span className="size-2 rounded-full bg-blocked" /> <b className="font-medium">Diblokir</b> <span className="text-muted-foreground">— tidak pernah terkirim</span></li>
          </ul>
        </Panel>
      </div>
    </div>
  )
}

function Otonomi() {
  const { role } = useRole()
  const isAdmin = role === "admin"
  const { data, mutate } = useSWR<SettingsSnapshot>("/api/settings", fetcher)
  const [draft, setDraft] = useState<Record<string, AutonomyMode> | null>(null)
  const [saving, setSaving] = useState(false)
  if (!data) return <SkeletonRows rows={6} />
  const modes = draft ?? data.otonomi
  const changed = AGENTS.some((a) => modes[a.id] !== data.otonomi[a.id])

  async function save() {
    setSaving(true)
    try {
      await mutate(await saveSettings({ otonomi: modes }), { revalidate: false })
      setDraft(null)
      toast.success("Mode otonomi tersimpan dan tercatat di Ledger")
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      {data.budget_terlampaui && (
        <p className="rounded-2xl border border-gold-500/40 bg-gold-100/60 px-4 py-3 text-[13px]">
          <b className="font-medium">Budget AI terlampaui.</b> Agen bermode Otonom sementara berjalan sebagai <b className="font-medium">Setujui dulu</b>.
        </p>
      )}
      <Panel className="divide-y divide-line">
        {AGENTS.map((a) => (
          <div key={a.id} className="flex flex-wrap items-center gap-4 px-5 py-4">
            <div className="min-w-[220px] flex-1">
              <div className="flex items-center gap-2">
                <span className="text-[13.5px] font-medium">{a.nama}</span>
                <span className="text-[11.5px] text-subtle-foreground">{a.prioritas}</span>
              </div>
              <div className="mt-0.5 text-[13px] text-muted-foreground">{AUTONOMY_HINT[modes[a.id]]}</div>
            </div>
            <AutonomyPicker
              value={modes[a.id]}
              readOnly={!isAdmin}
              onChange={(m) => setDraft({ ...modes, [a.id]: m })}
              allowOtonom={data.boleh_otonom.includes(a.id)}
              label={`Mode otonomi ${a.nama}`}
            />
          </div>
        ))}
      </Panel>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-[12.5px] text-muted-foreground">
          Brief pilot: mulai dari <b className="font-medium text-foreground">Setujui dulu</b>. Otonom hanya untuk jawaban katalog berisiko rendah, tetap lewat ClaimGuard.
        </p>
        {isAdmin ? (
          <div className="flex gap-2">
            <AButton variant="glass" size="sm" disabled={!changed || saving} onClick={() => setDraft(null)}>
              Batalkan
            </AButton>
            <AButton size="sm" disabled={!changed || saving} onClick={save}>
              Simpan
            </AButton>
          </div>
        ) : (
          <span className="text-[12.5px] text-subtle-foreground">Hanya Admin yang dapat mengubah.</span>
        )}
      </div>
    </div>
  )
}

function BudgetRow({ label, spent, cap }: { label: string; spent: number; cap: number }) {
  const pct = cap ? Math.min(100, (spent / cap) * 100) : 0
  return (
    <div className="px-5 py-5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[13.5px] font-medium">{label}</span>
        <span className="tabular text-[13px] text-muted-foreground">
          <b className="font-semibold text-foreground">{formatRp(spent, { decimals: true })}</b> / {formatRp(cap)}
        </span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-soft">
        <div className={cn("h-full rounded-full", pct >= 90 ? "bg-gold-500" : "bg-brand-500")} style={{ width: `${Math.max(1, pct)}%` }} />
      </div>
      <div className="tabular mt-1.5 text-[12px] text-subtle-foreground">{pct.toFixed(1).replace(".", ",")}% terpakai</div>
    </div>
  )
}

function BudgetEditor({ harian, bulanan, onSaved }: { harian: number; bulanan: number; onSaved: () => void }) {
  const [h, setH] = useState(String(harian))
  const [b, setB] = useState(String(bulanan))
  const [saving, setSaving] = useState(false)
  const changed = Number(h) !== harian || Number(b) !== bulanan

  async function save() {
    setSaving(true)
    try {
      await saveSettings({ anggaran: { harian_rp: Number(h), bulanan_rp: Number(b) } })
      onSaved()
      toast.success("Batas budget tersimpan dan tercatat di Ledger")
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-3 px-5 py-5">
      {[
        ["Batas harian (Rp)", h, setH],
        ["Batas bulanan (Rp)", b, setB],
      ].map(([label, val, set]) => (
        <label key={label as string} className="min-w-[160px] flex-1 space-y-1.5 text-[12.5px] font-medium">
          <span>{label as string}</span>
          <Input
            type="number"
            min={0}
            step={1000}
            value={val as string}
            onChange={(e) => (set as (v: string) => void)(e.target.value)}
            className="tabular h-9 rounded-[10px] bg-card"
          />
        </label>
      ))}
      <AButton size="sm" className="h-9" disabled={!changed || saving || h === "" || b === ""} onClick={save}>
        Simpan
      </AButton>
    </div>
  )
}

function Anggaran() {
  const { role } = useRole()
  const { data: status } = useSWR<Status>("/api/status", fetcher)
  const { data: live, mutate } = useSWR<AgentsStatus>("/api/agents/status", fetcher, { refreshInterval: 10000 })
  if (!status || !live) return <SkeletonRows rows={3} />
  const a = live.anggaran
  const data = status
  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_340px]">
      <Panel className="divide-y divide-line">
        <BudgetRow label="Batas harian" spent={a.terpakai_hari_ini_rp} cap={a.harian_rp} />
        <BudgetRow label="Batas bulanan" spent={a.terpakai_bulan_ini_rp} cap={a.bulanan_rp} />
        {role === "admin" && <BudgetEditor key={`${a.harian_rp}-${a.bulanan_rp}`} harian={a.harian_rp} bulanan={a.bulanan_rp} onSaved={() => mutate()} />}
      </Panel>
      <Panel className="space-y-3 p-5 text-[13px]">
        <h2 className="text-[14px] font-semibold">Saat batas terlewati</h2>
        <p className="text-muted-foreground">Semua agen otomatis turun ke mode <b className="font-medium text-foreground">Setujui dulu</b> sampai periode berikutnya.</p>
        <div className="h-px bg-line" />
        <div className="flex justify-between"><span className="text-muted-foreground">Model utama</span><span className="font-mono text-[12px]">{data.llm.aktif ? data.llm.model : "offline (deterministik)"}</span></div>
        <div className="flex justify-between"><span className="text-muted-foreground">Model pemeriksa</span><span className="font-mono text-[12px]">{data.llm.judge ?? "—"}</span></div>
        <p className="text-[12px] text-subtle-foreground">Nilai awal dari BUDGET_DAILY_RP dan BUDGET_MONTHLY_RP; Admin dapat mengubahnya di sini.</p>
      </Panel>
    </div>
  )
}

function PengaturanInner() {
  const [tab, setTab] = usePageTab(TABS, "kebijakan")
  return (
    <div>
      <PageHeader title="Pengaturan" description="Kebijakan agen, mode otonomi, batas biaya AI, dan Knowledge Base katalog. Hanya untuk Admin/Manajemen." />
      <PageTabs
        value={tab}
        onChange={setTab}
        items={[
          { value: "kebijakan", label: "Kebijakan" },
          { value: "otonomi", label: "Mode otonomi" },
          { value: "anggaran", label: "Budget AI" },
          { value: "katalog", label: "Katalog" },
        ]}
      />
      {tab === "kebijakan" && <Kebijakan />}
      {tab === "otonomi" && <Otonomi />}
      {tab === "anggaran" && <Anggaran />}
      {tab === "katalog" && <KatalogManager />}
    </div>
  )
}

export default function PengaturanPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={8} />}>
      <PengaturanInner />
    </Suspense>
  )
}
