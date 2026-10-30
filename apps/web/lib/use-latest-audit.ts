"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { api } from "@/lib/api"
import type { LatestAuditResponse } from "@/lib/types"

/** Interval polling status audit (ms). Atur lewat NEXT_PUBLIC_CLAIMGUARD_POLL_MS; minimum 3 detik. */
export const POLL_MS = Math.max(3000, Number(process.env.NEXT_PUBLIC_CLAIMGUARD_POLL_MS) || 10_000)
const TIMEOUT_MS = 10_000

type State = { data: LatestAuditResponse | null; error: string | null; loading: boolean; fetchedAt: Date | null }
const EMPTY: State = { data: null, error: null, loading: false, fetchedAt: null }

/**
 * Polling GET /api/compliance/latest-audit untuk satu draf. Hanya membaca status tersimpan — tidak pernah
 * memicu audit baru. Request sebelumnya dibatalkan bila draf berganti, komponen unmount, atau melewati batas waktu.
 */
export function useLatestAudit(draftId: number | null, intervalMs: number = POLL_MS) {
  const [state, setState] = useState<State>(EMPTY)
  const ctrlRef = useRef<AbortController | null>(null)

  const load = useCallback(async () => {
    if (draftId == null) return
    ctrlRef.current?.abort("superseded")
    const ctrl = new AbortController()
    ctrlRef.current = ctrl
    const timer = setTimeout(() => ctrl.abort("timeout"), TIMEOUT_MS)
    try {
      const data = await api<LatestAuditResponse>(`/api/compliance/latest-audit?draft_id=${draftId}`, { signal: ctrl.signal })
      if (!ctrl.signal.aborted) setState({ data, error: null, loading: false, fetchedAt: new Date() })
    } catch (err) {
      if (ctrl.signal.aborted && ctrl.signal.reason !== "timeout") return
      const message =
        ctrl.signal.reason === "timeout"
          ? "Status audit tidak termuat dalam 10 detik"
          : err instanceof Error
            ? err.message
            : "Gagal memuat status audit"
      setState((s) => ({ ...s, loading: false, error: message }))
    } finally {
      clearTimeout(timer)
    }
  }, [draftId])

  useEffect(() => {
    if (draftId == null) return
    const first = setTimeout(load, 0)
    const id = setInterval(load, intervalMs)
    return () => {
      clearTimeout(first)
      clearInterval(id)
      ctrlRef.current?.abort("unmount")
    }
  }, [draftId, intervalMs, load])

  /** Terapkan respons aksi (audit/tindakan) langsung tanpa menunggu polling berikutnya. */
  const apply = useCallback((data: LatestAuditResponse) => setState({ data, error: null, loading: false, fetchedAt: new Date() }), [])

  const current = draftId == null ? EMPTY : state.data?.draft && state.data.draft.id !== draftId ? { ...state, data: null, loading: true } : state
  return { ...current, loading: draftId != null && current.data == null && current.error == null, refresh: load, apply }
}
