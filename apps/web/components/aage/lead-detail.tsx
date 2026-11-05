"use client"

// Bagian drawer untuk data lead: verifikasi, confidence, asal data, riwayat skor, aktivitas, dan calon duplikat.

import { Check, Lightbulb, LoaderCircle, X } from "lucide-react"
import Link from "next/link"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { ApiError, api } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import type { KesalahanLead, LeadDetail, Prospect } from "@/lib/types"
import { cn } from "@/lib/utils"

import { AButton } from "./button"
import { SkeletonRows } from "./empty-state"

export const VERIFIKASI: Record<string, { label: string; cls: string }> = {
  belum: { label: "Belum diverifikasi", cls: "bg-soft text-muted-foreground" },
  perlu_tinjauan: { label: "Perlu tinjauan", cls: "bg-review-bg text-review" },
  terverifikasi: { label: "Terverifikasi", cls: "bg-ok-bg text-ok" },
  ditolak: { label: "Ditolak", cls: "bg-blocked-bg text-blocked" },
}

const input = "mt-0.5 h-9 w-full rounded-md border border-line bg-white px-2 text-[13px] outline-none focus:border-brand-500"

export function LangkahVerifikasi({ p, onUpdated }: { p: Prospect; onUpdated: (p: Prospect) => void }) {
  const [busy, setBusy] = useState(false)
  const v = VERIFIKASI[p.status_verifikasi] ?? VERIFIKASI.belum

  async function simpan(status: "terverifikasi" | "ditolak" | "belum", pesan: string) {
    setBusy(true)
    try {
      onUpdated(await api<Prospect>(`/api/prospects/${p.id}/verifikasi`, { method: "PUT", json: { status } }))
      toast.success(pesan)
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Verifikasi gagal disimpan")
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-start gap-2 rounded-lg border border-line bg-soft/60 p-3 text-[13px]">
        <Lightbulb className="mt-0.5 size-4 shrink-0 text-forest-700" aria-hidden />
        <div>
          <p className="font-medium">{p.langkah_berikutnya}</p>
          <p className="mt-0.5 text-[12px] text-subtle-foreground">Saran berdasarkan data lead, bukan izin menghubungi.</p>
        </div>
      </div>
      <div>
        <div className="mb-2 flex items-center justify-between">
          <h3 className="text-[13px] font-semibold">Verifikasi data</h3>
          <span className={cn("inline-flex h-6 items-center rounded-full px-2 text-[12px] font-medium", v.cls)}>{v.label}</span>
        </div>
        {p.alasan_tinjauan.length > 0 && (
          <ul className="mb-2 flex flex-wrap gap-1.5">
            {p.alasan_tinjauan.map((a) => (
              <li key={a} className="rounded-full bg-review-bg px-2 py-0.5 text-[12px] text-review">
                {a}
              </li>
            ))}
          </ul>
        )}
        {p.digabung_ke_id ? (
          <p className="text-[12px] text-subtle-foreground">Lead ini sudah digabung, jadi tidak bisa diubah lagi.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {p.verifikasi !== "terverifikasi" && (
              <AButton size="sm" disabled={busy} onClick={() => simpan("terverifikasi", "Lead ditandai terverifikasi")}>
                <Check className="size-3.5" /> Tandai terverifikasi
              </AButton>
            )}
            {p.verifikasi !== "ditolak" && (
              <AButton size="sm" variant="outline" disabled={busy} onClick={() => simpan("ditolak", "Lead ditolak")}>
                <X className="size-3.5" /> Tolak lead
              </AButton>
            )}
            {p.verifikasi !== "belum" && (
              <AButton size="sm" variant="outline" disabled={busy} onClick={() => simpan("belum", "Verifikasi dibatalkan")}>
                Batalkan keputusan
              </AButton>
            )}
          </div>
        )}
      </div>
    </section>
  )
}

export function RincianConfidence({ p, detail }: { p: Prospect; detail?: LeadDetail }) {
  return (
    <section>
      <div className="mb-2 flex items-end justify-between">
        <h3 className="text-[13px] font-semibold">Confidence data</h3>
        <span className="tabular text-[20px] leading-none font-semibold">{p.confidence != null ? p.confidence.toLocaleString("id-ID") : "—"}</span>
      </div>
      {detail ? (
        <ul className="grid gap-1 text-[12.5px] sm:grid-cols-2">
          {detail.rincian_confidence.map((r) => (
            <li key={r.faktor} className={cn("flex items-center gap-1.5", r.ada ? "text-foreground" : "text-subtle-foreground")}>
              {r.ada ? <Check className="size-3.5 text-ok" aria-hidden /> : <X className="size-3.5" aria-hidden />} {r.faktor}
              <span className="sr-only">{r.ada ? "ada" : "belum ada"}</span>
            </li>
          ))}
        </ul>
      ) : (
        <SkeletonRows rows={1} />
      )}
      <p className="mt-2 text-[12px] text-subtle-foreground">Mengukur kelengkapan data, bukan peluang lead membeli. Bobot masih draf.</p>
    </section>
  )
}

function LengkapiData({ p, segmen, onUpdated }: { p: Prospect; segmen: string[]; onUpdated: (p: Prospect) => void }) {
  const awal = {
    nama: p.nama,
    tipe: p.tipe,
    wilayah: p.wilayah,
    alamat: p.alamat_jalan_ada ? p.alamat : "",
    website: p.website ?? "",
    jam_buka: p.jam_buka ?? "",
    lat: p.lat != null ? String(p.lat) : "",
    lng: p.lng != null ? String(p.lng) : "",
    telepon: "",
  }
  const [isi, setIsi] = useState(awal)
  const [galat, setGalat] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    setIsi(awal)
    setGalat({})
  }, [p.id, p.diperbarui_pada]) // eslint-disable-line react-hooks/exhaustive-deps

  async function simpan(e: React.FormEvent) {
    e.preventDefault()
    const json: Record<string, string | number | null> = {}
    const salah: Record<string, string> = {}
    for (const k of Object.keys(awal) as (keyof typeof awal)[]) {
      if (isi[k] === awal[k]) continue
      const nilai = isi[k].trim()
      if (k !== "lat" && k !== "lng") json[k] = nilai || null
      else if (!nilai) json[k] = null
      else if (Number.isFinite(Number(nilai.replace(",", ".")))) json[k] = Number(nilai.replace(",", "."))
      else salah[k] = "Harus berupa angka desimal"
    }
    if (Object.keys(salah).length) {
      setGalat(salah)
      return
    }
    if (!Object.keys(json).length) {
      toast("Tidak ada data yang berubah")
      return
    }
    setBusy(true)
    setGalat({})
    try {
      onUpdated(await api<Prospect>(`/api/prospects/${p.id}/data`, { method: "PATCH", json }))
      toast.success("Data lead diperbarui, skor dihitung ulang")
    } catch (err) {
      const d = err instanceof ApiError ? (err.detail as { kesalahan?: KesalahanLead[] } | null) : null
      if (d?.kesalahan) setGalat(Object.fromEntries(d.kesalahan.map((k) => [k.kolom, k.alasan])))
      else toast.error(err instanceof Error ? err.message : "Data gagal disimpan")
    } finally {
      setBusy(false)
    }
  }

  function kolom(k: keyof typeof awal, label: string, tambahan: React.ComponentProps<"input"> = {}) {
    return (
      <label className="text-[12px] text-muted-foreground">
        {label}
        <input {...tambahan} value={isi[k]} aria-invalid={Boolean(galat[k])} onChange={(e) => setIsi((s) => ({ ...s, [k]: e.target.value }))} className={input} />
        {galat[k] && <span className="mt-0.5 block text-blocked">{galat[k]}</span>}
      </label>
    )
  }

  return (
    <details className="rounded-lg border border-line p-3">
      <summary className="cursor-pointer text-[13px] font-semibold">Lengkapi data</summary>
      <form onSubmit={simpan} className="mt-3 grid gap-2 sm:grid-cols-2">
        {kolom("nama", "Nama", { required: true, maxLength: 300 })}
        <label className="text-[12px] text-muted-foreground">
          Segmen
          <select value={isi.tipe} onChange={(e) => setIsi((s) => ({ ...s, tipe: e.target.value }))} className={input}>
            {[...new Set([p.tipe, ...segmen])].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          {galat.tipe && <span className="mt-0.5 block text-blocked">{galat.tipe}</span>}
        </label>
        {kolom("wilayah", "Wilayah", { required: true, maxLength: 200 })}
        {kolom("telepon", p.ada_wa || p.telepon ? "Nomor baru" : "Telepon", { maxLength: 60, inputMode: "tel", placeholder: p.telepon ? "Kosongkan kalau tidak berubah" : "" })}
        <div className="sm:col-span-2">{kolom("alamat", "Alamat", { maxLength: 600 })}</div>
        {kolom("website", "Website", { maxLength: 400 })}
        {kolom("jam_buka", "Jam buka", { maxLength: 300 })}
        {kolom("lat", "Lintang (lat)", { inputMode: "decimal" })}
        {kolom("lng", "Bujur (lng)", { inputMode: "decimal" })}
        {p.consent_status === "GRANTED" && <p className="text-[12px] text-review sm:col-span-2">Mengganti nomor membatalkan consent, karena consent melekat pada nomor lama.</p>}
        <div className="sm:col-span-2">
          <AButton size="sm" type="submit" disabled={busy}>
            {busy && <LoaderCircle className="size-3.5 animate-spin" />} Simpan data
          </AButton>
        </div>
      </form>
    </details>
  )
}

export function TabRiwayat({
  p,
  detail,
  galat,
  segmen,
  onUlang,
  onUpdated,
}: {
  p: Prospect
  detail?: LeadDetail
  galat?: unknown
  segmen: string[]
  onUlang: () => void
  onUpdated: (p: Prospect) => void
}) {
  if (galat && !detail) {
    return (
      <div role="alert" className="rounded-md bg-blocked-bg px-3 py-2 text-[13px] text-blocked">
        {galat instanceof Error ? galat.message : "Detail lead gagal dimuat."}
        <button type="button" className="ml-2 font-medium underline" onClick={onUlang}>
          Coba lagi
        </button>
      </div>
    )
  }
  if (!detail) return <SkeletonRows rows={5} />
  return (
    <div className="space-y-6">
      {!p.digabung_ke_id && <LengkapiData p={p} segmen={segmen} onUpdated={onUpdated} />}
      {detail.duplikat.length > 0 && (
        <section>
          <h3 className="mb-2 text-[13px] font-semibold">Calon duplikat</h3>
          <ul className="space-y-2 text-[12.5px]">
            {detail.duplikat.map((d) => (
              <li key={d.id} className="rounded-lg border border-review/30 bg-review-bg/40 p-3">
                <p className="font-medium">{d.lead.nama}</p>
                <p className="text-muted-foreground">{d.alasan.map((a) => a.keterangan).join("; ")}</p>
              </li>
            ))}
          </ul>
          <Link href="/leads/tinjauan" className="mt-2 inline-block text-[12.5px] font-medium text-forest-700 underline">
            Putuskan di antrean tinjauan
          </Link>
        </section>
      )}
      <section>
        <h3 className="mb-2 text-[13px] font-semibold">Asal data</h3>
        {detail.bukti.length === 0 ? (
          <p className="text-[12.5px] text-muted-foreground">Belum ada catatan asal data.</p>
        ) : (
          <ul className="space-y-2 text-[12.5px]">
            {detail.bukti.map((b) => (
              <li key={b.id} className="rounded-lg border border-line p-3">
                <p className="font-medium">{b.label}</p>
                <p className="break-words text-muted-foreground">{b.source_reference}</p>
                <p className="text-[11.5px] text-subtle-foreground">Dikumpulkan {formatDateTime(b.dikumpulkan_pada)}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section>
        <h3 className="mb-2 text-[13px] font-semibold">Riwayat skor</h3>
        {detail.riwayat_skor.length === 0 ? (
          <p className="text-[12.5px] text-muted-foreground">Belum ada riwayat skor.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-[12.5px]">
              <thead className="bg-soft text-left text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 font-medium">Waktu</th>
                  <th className="px-3 py-1.5 font-medium">Skor</th>
                  <th className="px-3 py-1.5 font-medium">Confidence</th>
                  <th className="px-3 py-1.5 font-medium">Versi</th>
                  <th className="px-3 py-1.5 font-medium">Pemicu</th>
                </tr>
              </thead>
              <tbody>
                {detail.riwayat_skor.map((r, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="px-3 py-1.5 whitespace-nowrap">{formatDateTime(r.dibuat_pada)}</td>
                    <td className="tabular px-3 py-1.5">{r.skor}</td>
                    <td className="tabular px-3 py-1.5">{r.confidence != null ? r.confidence.toLocaleString("id-ID") : "—"}</td>
                    <td className="px-3 py-1.5 font-mono text-[11.5px] whitespace-nowrap">{r.skor_versi}</td>
                    <td className="px-3 py-1.5">{r.pemicu.replace("_", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section>
        <h3 className="mb-2 text-[13px] font-semibold">Aktivitas</h3>
        {detail.aktivitas.length === 0 ? (
          <p className="text-[12.5px] text-muted-foreground">Belum ada aktivitas tercatat.</p>
        ) : (
          <ul className="space-y-2 text-[12.5px]">
            {detail.aktivitas.map((a) => (
              <li key={a.id} className="border-l-2 border-line pl-3">
                <p className="font-medium">{a.label}</p>
                {a.ringkasan && <p className="text-muted-foreground">{a.ringkasan}</p>}
                <p className="text-[11.5px] text-subtle-foreground">
                  {a.aktor} · {formatDateTime(a.pada)}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
