"use client"

import { useEffect, useState } from "react"
import useSWR from "swr"

import type { AutonomyMode } from "@/lib/agents"
import { api, fetcher, getToken } from "@/lib/api"

export type AgentState = "bekerja" | "menunggu" | "idle" | "jeda"

export type AgentLive = {
  id: string
  status: AgentState
  tugas: number
  biaya_rp: number
  antrean: number
  kerja: string
  terakhir: string | null
  mode: AutonomyMode
  /** Mode yang benar-benar berlaku (mis. turun ke "setujui" saat budget terlampaui). */
  mode_efektif: AutonomyMode
  alasan_mode: string | null
  jeda: boolean
}

export type AgentsStatus = {
  agen: AgentLive[]
  anggaran: {
    harian_rp: number
    bulanan_rp: number
    terpakai_hari_ini_rp: number
    terpakai_bulan_ini_rp: number
    terlampaui: boolean
  }
  diperbarui: string
}

export type SettingsSnapshot = {
  otonomi: Record<string, AutonomyMode>
  jeda: Record<string, boolean>
  anggaran: { harian_rp: number; bulanan_rp: number }
  budget_terlampaui: boolean
  boleh_otonom: string[]
}

export type SettingsPatch = Partial<{
  otonomi: Record<string, AutonomyMode>
  jeda: Record<string, boolean>
  anggaran: Partial<{ harian_rp: number; bulanan_rp: number }>
}>

export function saveSettings(patch: SettingsPatch) {
  return api<SettingsSnapshot>("/api/settings", { method: "PUT", json: patch })
}

/** Status agen dari Ledger: snapshot awal lewat SWR, lalu pembaruan langsung lewat SSE (menyambung ulang otomatis). */
export function useAgentStatus() {
  const swr = useSWR<AgentsStatus>("/api/agents/status", fetcher)
  const { mutate } = swr
  const [live, setLive] = useState(false)

  useEffect(() => {
    let stopped = false
    let ctrl: AbortController | null = null

    async function run() {
      while (!stopped) {
        ctrl = new AbortController()
        try {
          const res = await fetch("/api/agents/status/stream", {
            headers: { Authorization: `Bearer ${getToken() ?? ""}` },
            signal: ctrl.signal,
          })
          if (!res.ok || !res.body) throw new Error(`stream ${res.status}`)
          setLive(true)
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
                mutate(JSON.parse(line.slice(6)) as AgentsStatus, { revalidate: false })
              } catch {
                /* potongan rusak diabaikan */
              }
            }
          }
        } catch (e) {
          if ((e as Error).name === "AbortError") return
        }
        setLive(false)
        if (!stopped) await new Promise((r) => setTimeout(r, 3000))
      }
    }

    run()
    return () => {
      stopped = true
      ctrl?.abort()
    }
  }, [mutate])

  return { ...swr, live }
}
