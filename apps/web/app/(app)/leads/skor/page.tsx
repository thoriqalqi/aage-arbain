"use client"

import { LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { SkeletonRows } from "@/components/aage/empty-state"
import { GalatMuat, LeadsNav } from "@/components/aage/leads-nav"
import { PageHeader, Panel } from "@/components/aage/panel"
import { Pill } from "@/components/aage/status"
import { ApiError, api, fetcher } from "@/lib/api"
import { useRole } from "@/lib/rbac"
import type { LeadKonfigurasi } from "@/lib/types"

const field = "mt-0.5 h-10 w-full rounded-[10px] border border-line bg-white px-3 text-[14px] outline-none focus:border-brand-500 disabled:bg-soft"
const BOBOT: { kunci: keyof LeadKonfigurasi["bobot"]; label: string; ket: string }[] = [
  { kunci: "geo_maks", label: "Lokasi", ket: "Poin maksimal untuk zona jarak terbaik dari gudang" },
  { kunci: "telepon", label: "Telepon", ket: "Nomor telepon tersedia" },
  { kunci: "jam", label: "Jam buka", ket: "Jam operasional tercatat" },
  { kunci: "jalan", label: "Alamat jalan", ket: "Alamat sampai nama jalan" },
]

export default function PengaturanSkorPage() {
  const { actual } = useRole()
  const bolehUbah = actual === "admin"
  const { data, error, mutate } = useSWR<LeadKonfigurasi>("/api/prospects/konfigurasi", fetcher)
  const [bobot, setBobot] = useState<Record<string, string>>({})
  const [ambang, setAmbang] = useState("")
  const [segmen, setSegmen] = useState("")
  const [busy, setBusy] = useState(false)
  const [menghitung, setMenghitung] = useState(false)
  const [galat, setGalat] = useState<string | null>(null)

  useEffect(() => {
    if (!data) return
    setBobot(Object.fromEntries(Object.entries(data.bobot).map(([k, v]) => [k, String(v)])))
    setAmbang(String(data.ambang_confidence))
    setSegmen(data.segmen.join("\n"))
  }, [data])

  const jumlah = BOBOT.reduce((n, b) => n + (Number(bobot[b.kunci]) || 0), 0)
  const daftarSegmen = segmen.split("\n").map((s) => s.trim()).filter(Boolean)

  async function simpan(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setGalat(null)
    try {
      const baru = await api<LeadKonfigurasi>("/api/prospects/konfigurasi", {
        method: "PUT",
        json: { bobot: Object.fromEntries(Object.entries(bobot).map(([k, v]) => [k, Number(v)])), ambang_confidence: Number(ambang), segmen: daftarSegmen },
      })
      await mutate(baru, false)
      toast.success(baru.versi === data?.versi ? "Pengaturan tersimpan" : `Tersimpan sebagai ${baru.versi}. Skor lama tetap sampai dihitung ulang.`)
    } catch (err) {
      setGalat(err instanceof Error ? err.message : "Pengaturan gagal disimpan")
    } finally {
      setBusy(false)
    }
  }

  async function hitungUlang() {
    setMenghitung(true)
    try {
      const r = await api<{ versi: string; jumlah: number; berubah: number }>("/api/prospects/skor/hitung-ulang", { method: "POST" })
      toast.success(`${r.jumlah} lead diperiksa, ${r.berubah} berubah (${r.versi})`)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Penghitungan ulang gagal")
    } finally {
      setMenghitung(false)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Pengaturan skor" description="Bobot Opportunity Score, ambang confidence, dan daftar segmen. Setiap perubahan bobot membuat versi skor baru." />
      <LeadsNav />
      {error && !data ? (
        <GalatMuat error={error} onUlang={() => mutate()} />
      ) : !data ? (
        <SkeletonRows rows={5} />
      ) : (
        <>
          <div className="flex items-start gap-2 rounded-[12px] border border-review/30 bg-review-bg px-4 py-3 text-[13px] text-review">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>Semua bobot masih draf dan belum disetujui CV Arba&apos;in, jadi skor bersifat sementara. Skor tinggi bukan izin menghubungi.</span>
          </div>
          <form onSubmit={simpan} className="space-y-4">
            <Panel className="space-y-4 p-5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-[15px] font-semibold">Bobot skor</h2>
                <Pill>Versi {data.versi}</Pill>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                {BOBOT.map((b) => (
                  <label key={b.kunci} className="text-[12px] text-muted-foreground">
                    {b.label}
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step="any"
                      disabled={!bolehUbah}
                      value={bobot[b.kunci] ?? ""}
                      onChange={(e) => setBobot((s) => ({ ...s, [b.kunci]: e.target.value }))}
                      className={field}
                    />
                    <span className="mt-0.5 block text-subtle-foreground">{b.ket}</span>
                  </label>
                ))}
              </div>
              <p className={jumlah === 100 ? "text-[13px] text-ok" : "text-[13px] font-medium text-blocked"} role="status">
                Jumlah bobot: {jumlah.toLocaleString("id-ID")} dari 100
              </p>
              <label className="block max-w-xs text-[12px] text-muted-foreground">
                Penalti jaringan nasional
                <input
                  type="number"
                  min={0}
                  max={100}
                  step="any"
                  disabled={!bolehUbah}
                  value={bobot.penalti_jaringan ?? ""}
                  onChange={(e) => setBobot((s) => ({ ...s, penalti_jaringan: e.target.value }))}
                  className={field}
                />
                <span className="mt-0.5 block text-subtle-foreground">Dikurangkan kalau toko bagian dari jaringan nasional</span>
              </label>
            </Panel>
            <Panel className="grid gap-4 p-5 md:grid-cols-2">
              <label className="text-[12px] text-muted-foreground">
                Ambang confidence
                <input type="number" min={0} max={1} step={0.1} disabled={!bolehUbah} value={ambang} onChange={(e) => setAmbang(e.target.value)} className={field} />
                <span className="mt-0.5 block text-subtle-foreground">Di bawah angka ini lead masuk antrean tinjauan</span>
              </label>
              <label className="text-[12px] text-muted-foreground">
                Segmen, satu per baris
                <textarea rows={4} disabled={!bolehUbah} value={segmen} onChange={(e) => setSegmen(e.target.value)} className="mt-0.5 w-full rounded-[10px] border border-line bg-white p-3 text-[14px] outline-none focus:border-brand-500 disabled:bg-soft" />
                <span className="mt-0.5 block text-subtle-foreground">Segmen final perlu dikonfirmasi CV Arba&apos;in</span>
              </label>
            </Panel>
            {galat && (
              <div role="alert" className="rounded-md bg-blocked-bg px-3 py-2 text-[13px] text-blocked">
                {galat}
              </div>
            )}
            {bolehUbah ? (
              <div className="flex flex-wrap items-center gap-2">
                <AButton type="submit" disabled={busy || jumlah !== 100 || !daftarSegmen.length}>
                  {busy && <LoaderCircle className="size-4 animate-spin" />} Simpan pengaturan
                </AButton>
                <AButton type="button" variant="outline" disabled={menghitung} onClick={hitungUlang}>
                  {menghitung ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />} Hitung ulang semua skor
                </AButton>
                <span className="text-[12px] text-subtle-foreground">Skor lama tetap sampai dihitung ulang. Riwayatnya tersimpan per lead.</span>
              </div>
            ) : (
              <p className="text-[12.5px] text-muted-foreground">Hanya admin yang bisa mengubah pengaturan ini.</p>
            )}
          </form>
        </>
      )}
    </div>
  )
}
