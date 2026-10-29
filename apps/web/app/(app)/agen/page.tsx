"use client"

import { Box, Pause, Play, ScrollText } from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { AutonomyPicker } from "@/components/aage/autonomy-picker"
import { IsoOffice, type DeskState } from "@/components/aage/iso-office"
import { PageHeader, Panel, SampleNote } from "@/components/aage/panel"
import { AGENTS, AUTONOMY_HINT, type AutonomyMode } from "@/lib/agents"
import { fetcher } from "@/lib/api"
import { contactName, formatRp, relativeTime } from "@/lib/format"
import { INTENT_LABEL, type Approval } from "@/lib/types"
import { cn } from "@/lib/utils"

// Status & statistik per agen: data contoh sampai GET /api/v1/agents (+ SSE) tersedia.
const SAMPLE: Record<string, { state: DeskState; tugas: number; antrean: number; biaya: number; kerja: string }> = {
  orchestrator: { state: "bekerja", tugas: 64, antrean: 2, biaya: 310, kerja: "Merutekan 2 tugas ke Sales Assistant" },
  opportunity: { state: "idle", tugas: 12, antrean: 0, biaya: 140, kerja: "Menunggu wilayah baru untuk dipetakan" },
  sales: { state: "menunggu", tugas: 38, antrean: 3, biaya: 920, kerja: "Draf jawaban harga menunggu staf" },
  content: { state: "bekerja", tugas: 5, antrean: 1, biaya: 480, kerja: "Menyusun artikel SEO madu stamina" },
  claimguard: { state: "bekerja", tugas: 71, antrean: 0, biaya: 95, kerja: "Memeriksa 3 kalimat draf konten" },
  evaluation: { state: "idle", tugas: 1, antrean: 0, biaya: 20, kerja: "Laporan harian dijadwalkan 23.00" },
}

const STATE_META: Record<DeskState, { label: string; cls: string; dot: string }> = {
  bekerja: { label: "Bekerja", cls: "bg-ok-bg text-ok", dot: "bg-brand-500" },
  menunggu: { label: "Menunggu approval", cls: "bg-escalate-bg text-escalate", dot: "bg-gold-500" },
  idle: { label: "Siaga", cls: "bg-soft text-muted-foreground", dot: "bg-forest-700" },
  jeda: { label: "Dijeda", cls: "bg-soft text-muted-foreground", dot: "bg-subtle-foreground" },
}

export default function AgenPage() {
  const [selected, setSelected] = useState("sales")
  const [paused, setPaused] = useState<Record<string, boolean>>({})
  const [modes, setModes] = useState<Record<string, AutonomyMode>>(() => Object.fromEntries(AGENTS.map((a) => [a.id, a.mode])))
  const { data: ap } = useSWR<{ items: Approval[] }>("/api/approvals?status=menunggu", fetcher, { refreshInterval: 8000 })

  const stateOf = (id: string): DeskState => (paused[id] ? "jeda" : SAMPLE[id].state)
  const agent = AGENTS.find((a) => a.id === selected)!
  const s = SAMPLE[agent.id]
  const st = STATE_META[stateOf(agent.id)]
  const queue = agent.id === "sales" || agent.id === "orchestrator" ? (ap?.items ?? []) : []
  const totalTasks = Object.values(SAMPLE).reduce((n, x) => n + x.tugas, 0)
  const active = AGENTS.filter((a) => stateOf(a.id) === "bekerja").length

  return (
    <div>
      <PageHeader
        title="Agen"
        description="Kantor virtual enam agen. Pilih meja untuk melihat pekerjaan, antrean, dan mode otonominya."
        actions={
          <Link href="/dashboard" className="btn-glass inline-flex h-8 items-center gap-1.5 rounded-[10px] px-3 text-[13px] font-medium">
            <Box className="size-4 text-muted-foreground" /> Simulasi 3D
          </Link>
        }
      />

      <div className="grid gap-5 xl:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <Panel className="overflow-hidden">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-line px-5 py-3.5 text-[13px]">
              <span>
                <b className="tabular font-semibold">{active}</b> <span className="text-muted-foreground">dari 6 agen bekerja</span>
              </span>
              <span>
                <b className="tabular font-semibold">{totalTasks}</b> <span className="text-muted-foreground">tugas hari ini</span>
              </span>
              <div className="ml-auto flex flex-wrap gap-4 text-[12px] text-muted-foreground">
                {(["bekerja", "menunggu", "idle", "jeda"] as const).map((k) => (
                  <span key={k} className="inline-flex items-center gap-1.5">
                    <span className={cn("size-2 rounded-full", STATE_META[k].dot)} /> {STATE_META[k].label}
                  </span>
                ))}
              </div>
            </div>
            <div className="bg-canvas px-2 py-4 sm:px-6">
              <IsoOffice desks={AGENTS.map((a) => ({ id: a.id, label: a.singkat, state: stateOf(a.id) }))} selected={selected} onSelect={setSelected} />
            </div>
          </Panel>
          <SampleNote>Status dan statistik agen masih data contoh. Akan tersambung ke stream SSE agen saat endpoint siap; antrean approval sudah memakai data API.</SampleNote>
        </div>

        <Panel className="flex flex-col self-start">
          <div className="border-b border-line p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-[20px] text-forest-900">{agent.nama}</h2>
                <p className="mt-1 text-[13px] text-muted-foreground">{agent.fungsi}</p>
              </div>
            </div>
            <span className={cn("mt-3 inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium", st.cls)}>
              <span className={cn("size-1.5 rounded-full", st.dot)} /> {st.label}
            </span>
            <p className="mt-3 text-[13px]">{paused[agent.id] ? "Agen dijeda oleh staf." : s.kerja}</p>
          </div>

          <dl className="grid grid-cols-3 divide-x divide-line border-b border-line text-center">
            {[
              ["Tugas", String(s.tugas)],
              ["Antrean", String(queue.length || s.antrean)],
              ["Biaya", formatRp(s.biaya)],
            ].map(([k, v]) => (
              <div key={k} className="px-2 py-4">
                <dt className="text-[12px] text-muted-foreground">{k}</dt>
                <dd className="tabular mt-1 text-[16px] font-semibold">{v}</dd>
              </div>
            ))}
          </dl>

          <div className="border-b border-line p-5">
            <div className="mb-2.5 text-[12px] font-medium tracking-[0.08em] text-subtle-foreground uppercase">Mode otonomi</div>
            <AutonomyPicker
              size="sm"
              value={modes[agent.id]}
              onChange={(m) => setModes((x) => ({ ...x, [agent.id]: m }))}
              allowOtonom={agent.bolehOtonom}
              label={`Mode otonomi ${agent.nama}`}
            />
            <p className="mt-2 text-[12.5px] text-muted-foreground">{AUTONOMY_HINT[modes[agent.id]]}</p>
          </div>

          <div className="border-b border-line p-5">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[12px] font-medium tracking-[0.08em] text-subtle-foreground uppercase">Antrean</span>
              {queue.length > 0 && (
                <Link href="/approval" className="text-[12.5px] font-medium text-brand-600 hover:underline">
                  Buka approval
                </Link>
              )}
            </div>
            {queue.length === 0 ? (
              <p className="text-[13px] text-muted-foreground">{s.antrean ? `${s.antrean} tugas internal menunggu giliran.` : "Tidak ada antrean."}</p>
            ) : (
              <ul className="space-y-2.5">
                {queue.slice(0, 4).map((a) => (
                  <li key={a.id}>
                    <Link href={`/approval?id=${a.id}`} className="block rounded-xl border border-line px-3 py-2.5 hover:border-brand-300">
                      <div className="flex items-center justify-between gap-2 text-[13px]">
                        <span className="truncate font-medium">{contactName(a.contact)}</span>
                        <span className="shrink-0 text-[11.5px] text-subtle-foreground">{relativeTime(a.dibuat_pada)}</span>
                      </div>
                      <div className="mt-0.5 truncate text-[12px] text-muted-foreground">
                        {INTENT_LABEL[a.intent ?? ""] ?? a.intent} · {a.alasan}
                      </div>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="flex gap-2 p-5">
            <AButton variant="glass" size="sm" className="flex-1" onClick={() => setPaused((p) => ({ ...p, [agent.id]: !p[agent.id] }))}>
              {paused[agent.id] ? <Play className="size-4" /> : <Pause className="size-4" />}
              {paused[agent.id] ? "Lanjutkan" : "Jeda"}
            </AButton>
            <Link href="/compliance?tab=ledger" className="btn-liquid inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-[10px] text-[13px] font-medium">
              <ScrollText className="size-4" /> Lihat log
            </Link>
          </div>
        </Panel>
      </div>
    </div>
  )
}
