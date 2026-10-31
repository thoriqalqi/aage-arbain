"use client"

// Klien API: semua request lewat /api (di-rewrite Next.js ke FastAPI), token JWT di localStorage.

const TOKEN_KEY = "aage.token"
const USER_KEY = "aage.user"

export type SessionUser = { id: number; nama: string; email: string; role: "admin" | "staf" | "marketing" }

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

function safeGet(key: string): string | null {
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

export function getToken(): string | null {
  return typeof window === "undefined" ? null : safeGet(TOKEN_KEY)
}

export function getUser(): SessionUser | null {
  if (typeof window === "undefined") return null
  const raw = safeGet(USER_KEY)
  try {
    return raw ? (JSON.parse(raw) as SessionUser) : null
  } catch {
    return null
  }
}

export function saveSession(token: string, user: SessionUser) {
  try {
    window.localStorage.setItem(TOKEN_KEY, token)
    window.localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    /* mode privat: sesi hanya di memori tab ini */
  }
}

export function clearSession() {
  try {
    window.localStorage.removeItem(TOKEN_KEY)
    window.localStorage.removeItem(USER_KEY)
  } catch {
    /* abaikan */
  }
}

function messageFrom(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail
  if (detail && typeof detail === "object" && "pesan" in detail) return String((detail as { pesan: unknown }).pesan)
  return fallback
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const token = getToken()
  if (token) headers.set("Authorization", `Bearer ${token}`)
  let body = init.body
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json")
    body = JSON.stringify(init.json)
  }
  const res = await fetch(path.startsWith("/api") ? path : `/api${path}`, { ...init, headers, body })
  if (res.status === 401 && typeof window !== "undefined" && !path.includes("/auth/login")) {
    clearSession()
    if (!window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/chat")) {
      window.location.href = "/login"
    }
  }
  const ct = res.headers.get("content-type") || ""
  const data = ct.includes("application/json") ? await res.json() : await res.text()
  if (!res.ok) {
    const detail = typeof data === "object" && data && "detail" in data ? (data as { detail: unknown }).detail : data
    throw new ApiError(res.status, messageFrom(detail, `Permintaan gagal (${res.status})`), detail)
  }
  return data as T
}

export const fetcher = <T,>(path: string) => api<T>(path)

/** Unduh file dari API (dengan token) lalu simpan lewat browser. */
export async function unduh(path: string, namaFile: string): Promise<void> {
  const headers = new Headers()
  const token = getToken()
  if (token) headers.set("Authorization", `Bearer ${token}`)
  const res = await fetch(path, { headers })
  if (!res.ok) {
    const alasan =
      res.status === 404
        ? "file tidak ditemukan di server API — kemungkinan server API belum diperbarui/di-restart"
        : res.status === 401 || res.status === 403
          ? "perlu login sebagai admin"
          : `server membalas ${res.status}`
    throw new ApiError(res.status, `Unduhan gagal: ${alasan}.`, null)
  }
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement("a")
  a.href = url
  a.download = namaFile
  a.click()
  URL.revokeObjectURL(url)
}
