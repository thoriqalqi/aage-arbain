"use client"

import { Box, Pause, Play, ScrollText, TriangleAlert } from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { AutonomyPicker } from "@/components/aage/autonomy-picker"
import { IsoOffice, type DeskState } from "@/components/aage/iso-office"
import { PageHeader, Panel } from "@/components/aage/panel"
import { AGENTS, AUTONOMY_HINT, AUTONOMY_LABEL, type AutonomyMode } from "@/lib/agents"
import { fetcher } from "@/lib/api"
import { contactName, formatRp, relativeTime } from "@/lib/format"
import { useRole } from "@/lib/rbac"
import { INTENT_LABEL, type Approval } from "@/lib/types"
import { saveSettings, useAgentStatus, type AgentLive, type SettingsPatch } from "@/lib/use-agent-status"
import { cn } from "@/lib/utils"

const STATE_META: Record<DeskState, { label: string; cls: string; dot: string }> = {
  bekerja: { label: "Bekerja", cls: "bg-ok-bg text-ok", dot: "bg-brand-500" },
  menunggu: { label: "Menunggu approval", cls: "bg-escalate-bg text-escalate", dot: "bg-gold-500" },
  idle: { label: "Siaga", cls: "bg-soft text-muted-foreground", dot: "bg-forest-700" },
  jeda: { label: "Dijeda", cls: "bg-soft text-muted-foreground", dot: "bg-subtle-foreground" },
}

function fallback(id: string, mode: AutonomyMode): AgentLive {
  return { id, status: "idle", tugas: 0, biaya_rp: 0, antrean: 0, kerja: "Memuat status…", terakhir: null, mode,
    mode_efektif: mode, alasan_mode: null, jeda: false }
}

export default function AgenPage() {
  const [selected, setSelected] = useState("sales")
  const [saving, setSaving] = useState(false)
  const { role } = useRole()
  const isAdmin = role === "admin"
  const { data, live, mutate } = useAgentStatus()
  const { data: ap } = useSWR<{ items: Approval[] }>("/api/approvals?status=menunggu", fetcher, { refreshInterval: 8000 })

  const byId = Object.fromEntries((data?.agen ?? []).map((a) => [a.id, a]))
  const stat = (id: string) => byId[id] ?? fallback(id, AGENTS.find((a) => a.id === id)!.mode)
  const agent = AGENTS.find((a) => a.id === selected)!
  const s = stat(agent.id)
  const st = STATE_META[s.status]
  const queue = agent.id === "sales" ? (ap?.items ?? []) : []
  const totalTasks = (data?.agen ?? []).reduce((n, x) => n + x.tugas, 0)
  const active = (data?.agen ?? []).filter((a) => a.status === "bekerja").length

  async function apply(patch: SettingsPatch, ok: string) {
    setSaving(true)
    try {
      await saveSettings(patch)
      await mutate()
      toast.success(ok)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="Agen"
        description="Kantor virtual enam agen. Status dihitung langsung dari Ledger; pilih meja untuk melihat pekerjaan, antrean, dan mode otonominya."
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
              <span className="inline-flex items-center gap-1.5 text-[12px] font-medium" title={live ? "Tersambung ke stream status" : "Menyambung ulang…"}>
                <span className={cn("size-2 rounded-full", live ? "breathe bg-brand-500" : "bg-subtle-foreground")} />
                {live ? "Live" : "Offline"}
              </span>
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
              <IsoOffice desks={AGENTS.map((a) => ({ id: a.id, label: a.singkat, state: stat(a.id).status }))} selected={selected} onSelect={setSelected} />
            </div>
          </Panel>
          {data?.anggaran.terlampaui && (
            <div className="flex items-start gap-2.5 rounded-2xl border border-gold-500/40 bg-gold-100/60 px-4 py-3 text-[13px]">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-gold-600" />
              <span>
                <b className="font-medium">Budget AI terlampaui.</b> Agen otonom otomatis kembali ke <b className="font-medium">Setujui dulu</b> sampai periode berikutnya.
              </span>
            </div>
          )}
        </div>

        <Panel className="flex flex-col self-start">
          <div className="border-b border-line p-5">
            <h2 className="font-display text-[20px] text-forest-900">{agent.nama}</h2>
            <p className="mt-1 text-[13px] text-muted-foreground">{agent.fungsi}</p>
            <span className={cn("mt-3 inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-medium", st.cls)}>
              <span className={cn("size-1.5 rounded-full", st.dot)} /> {st.label}
            </span>
            <p className="mt-3 text-[13px]">{s.jeda ? "Agen dijeda oleh staf." : s.kerja}</p>
            {s.terakhir && <p className="mt-1 text-[12px] text-subtle-foreground">Aktivitas terakhir {relativeTime(s.terakhir)}</p>}
          </div>

          <dl className="grid grid-cols-3 divide-x divide-line border-b border-line text-center">
            {[
              ["Tugas hari ini", String(s.tugas)],
              ["Antrean", String(queue.length || s.antrean)],
              ["Biaya AI", formatRp(s.biaya_rp, { decimals: true })],
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
              value={s.mode}
              readOnly={!isAdmin || saving}
              onChange={(m) => apply({ otonomi: { [agent.id]: m } }, `${agent.nama}: mode ${AUTONOMY_LABEL[m]}`)}
              allowOtonom={agent.bolehOtonom}
              label={`Mode otonomi ${agent.nama}`}
            />
            <p className="mt-2 text-[12.5px] text-muted-foreground">{AUTONOMY_HINT[s.mode]}</p>
            {s.alasan_mode && <p className="mt-1.5 text-[12.5px] font-medium text-gold-600">{s.alasan_mode}</p>}
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
              <p className="text-[13px] text-muted-foreground">Tidak ada antrean.</p>
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

          <div className="p-5">
            <div className="flex gap-2">
              <AButton
                variant="glass"
                size="sm"
                className="flex-1"
                disabled={!isAdmin || saving}
                title={isAdmin ? undefined : "Hanya Admin yang dapat menjeda agen"}
                onClick={() => apply({ jeda: { [agent.id]: !s.jeda } }, `${agent.nama} ${s.jeda ? "dilanjutkan" : "dijeda"}`)}
              >
                {s.jeda ? <Play className="size-4" /> : <Pause className="size-4" />}
                {s.jeda ? "Lanjutkan" : "Jeda"}
              </AButton>
              <Link href="/compliance?tab=ledger" className="btn-liquid inline-flex h-8 flex-1 items-center justify-center gap-1.5 rounded-[10px] text-[13px] font-medium">
                <ScrollText className="size-4" /> Lihat log
              </Link>
            </div>
            {agent.id !== "sales" && (
              <p className="mt-3 text-[12px] text-subtle-foreground">
                Saat ini hanya Sales Assistant yang mengirim pesan otomatis. Jeda dan mode agen lain tercatat di Ledger dan dipakai saat agen tersebut diaktifkan.
              </p>
            )}
          </div>
        </Panel>
      </div>
    </div>
  )
}
