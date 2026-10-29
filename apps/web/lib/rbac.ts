"use client"

// RBAC sisi UI (Brief §4). Akses sebenarnya tetap ditegakkan di API — ini hanya menyusun menu
// dan menampilkan layar "akses dibatasi" agar pengguna tidak tersesat.

import { useEffect, useState } from "react"

import { getUser, type SessionUser } from "@/lib/api"

export type Role = "admin" | "marketing" | "sales"

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin / Manajemen",
  marketing: "Marketing",
  sales: "Sales B2B",
}

/** Peta role backend → role UI. Backend lama memakai "staf" untuk tim penjualan. */
export function normalizeRole(raw: string | null | undefined): Role {
  if (raw === "admin" || raw === "manajemen") return "admin"
  if (raw === "marketing") return "marketing"
  return "sales"
}

/** Layar yang boleh dibuka per role. Admin membuka semua. */
const ACCESS: Record<Role, string[] | "all"> = {
  admin: "all",
  marketing: ["/", "/konten", "/compliance", "/approval"],
  sales: ["/", "/leads", "/inbox", "/approval"],
}

export function canAccess(role: Role, pathname: string): boolean {
  const list = ACCESS[role]
  if (list === "all") return true
  return list.some((p) => (p === "/" ? pathname === "/" : pathname === p || pathname.startsWith(p + "/")))
}

// Admin bisa melihat dashboard sebagai role lain (pratinjau UI saja, tidak mengubah hak di API).
const PREVIEW_KEY = "aage.role.preview"
const EVENT = "aage:role-preview"

export function setRolePreview(role: Role | null) {
  try {
    if (role) window.localStorage.setItem(PREVIEW_KEY, role)
    else window.localStorage.removeItem(PREVIEW_KEY)
  } catch {
    /* abaikan */
  }
  window.dispatchEvent(new Event(EVENT))
}

function readPreview(): Role | null {
  try {
    const v = window.localStorage.getItem(PREVIEW_KEY)
    return v === "admin" || v === "marketing" || v === "sales" ? v : null
  } catch {
    return null
  }
}

export type RoleState = { user: SessionUser | null; actual: Role; role: Role; previewing: boolean }

export function useRole(): RoleState {
  const [state, setState] = useState<RoleState>({ user: null, actual: "sales", role: "sales", previewing: false })
  useEffect(() => {
    const sync = () => {
      const user = getUser()
      const actual = normalizeRole(user?.role)
      const preview = actual === "admin" ? readPreview() : null
      setState({ user, actual, role: preview ?? actual, previewing: preview != null && preview !== actual })
    }
    sync()
    window.addEventListener(EVENT, sync)
    window.addEventListener("storage", sync)
    return () => {
      window.removeEventListener(EVENT, sync)
      window.removeEventListener("storage", sync)
    }
  }, [])
  return state
}
