"use client"

import { LoaderCircle } from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ApiError, api } from "@/lib/api"
import type { KesalahanLead, Prospect } from "@/lib/types"

import { AButton } from "./button"

const KOSONG = { nama: "", tipe: "", wilayah: "", alamat: "", telepon: "", website: "", lat: "", lng: "", jam_buka: "", referensi: "" }
const input = "mt-0.5 h-9 w-full rounded-md border border-line bg-white px-2 text-[13px] outline-none focus:border-brand-500 aria-[invalid=true]:border-blocked"

export function LeadBaru({
  open,
  segmen,
  onClose,
  onCreated,
  onBukaLead,
}: {
  open: boolean
  segmen: string[]
  onClose: () => void
  onCreated: (p: Prospect) => void
  onBukaLead: (id: number) => void
}) {
  const [isi, setIsi] = useState(KOSONG)
  const [galat, setGalat] = useState<Record<string, string>>({})
  const [kembar, setKembar] = useState<{ id: number; pesan: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) {
      setIsi({ ...KOSONG, tipe: segmen[0] ?? "" })
      setGalat({})
      setKembar(null)
    }
  }, [open, segmen])

  function kolom(nama: keyof typeof KOSONG, label: string, tambahan: React.ComponentProps<"input"> = {}) {
    return (
      <label className="text-[12px] text-muted-foreground">
        {label}
        <input {...tambahan} value={isi[nama]} aria-invalid={Boolean(galat[nama])} onChange={(e) => setIsi((s) => ({ ...s, [nama]: e.target.value }))} className={input} />
        {galat[nama] && <span className="mt-0.5 block text-blocked">{galat[nama]}</span>}
      </label>
    )
  }

  async function simpan(e: React.FormEvent) {
    e.preventDefault()
    const angka = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")))
    const salah: Record<string, string> = {}
    for (const k of ["lat", "lng"] as const) {
      const n = angka(isi[k])
      if (n !== null && !Number.isFinite(n)) salah[k] = "Harus berupa angka desimal"
    }
    setGalat(salah)
    if (Object.keys(salah).length) return
    setBusy(true)
    setKembar(null)
    try {
      const teks = (v: string) => v.trim() || null
      const hasil = await api<Prospect & { calon_duplikat: { nama: string }[] }>("/api/prospects", {
        method: "POST",
        json: {
          nama: isi.nama,
          tipe: isi.tipe,
          wilayah: isi.wilayah,
          alamat: teks(isi.alamat),
          telepon: teks(isi.telepon),
          website: teks(isi.website),
          lat: angka(isi.lat),
          lng: angka(isi.lng),
          jam_buka: teks(isi.jam_buka),
          referensi: teks(isi.referensi),
        },
      })
      if (hasil.calon_duplikat.length) toast.warning(`Lead tersimpan, mirip dengan ${hasil.calon_duplikat[0].nama}. Periksa di antrean tinjauan.`)
      else toast.success("Lead tersimpan. Consent masih perlu dicatat sebelum promosi.")
      onCreated(hasil)
    } catch (err) {
      const d = err instanceof ApiError ? (err.detail as { kode?: string; lead_id?: number; pesan?: string; kesalahan?: KesalahanLead[] } | null) : null
      if (d?.kode === "VALIDASI" && d.kesalahan) setGalat(Object.fromEntries(d.kesalahan.map((k) => [k.kolom, k.alasan])))
      else if (d?.kode === "DUPLIKAT" && d.lead_id) setKembar({ id: d.lead_id, pesan: d.pesan ?? "Lead ini sudah ada" })
      else if (err instanceof ApiError && err.status === 422) toast.error("Ada isian yang formatnya salah. Lat dan lng harus angka.")
      else toast.error(err instanceof Error ? err.message : "Lead gagal disimpan")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Tambah lead</DialogTitle>
          <DialogDescription>Isi yang benar-benar diketahui. Yang kosong ditandai perlu tinjauan, bukan ditebak.</DialogDescription>
        </DialogHeader>
        <form onSubmit={simpan} className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">{kolom("nama", "Nama toko", { required: true, maxLength: 300 })}</div>
          <label className="text-[12px] text-muted-foreground">
            Segmen
            <select value={isi.tipe} aria-invalid={Boolean(galat.tipe)} onChange={(e) => setIsi((s) => ({ ...s, tipe: e.target.value }))} className={input}>
              {segmen.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            {galat.tipe && <span className="mt-0.5 block text-blocked">{galat.tipe}</span>}
          </label>
          {kolom("wilayah", "Wilayah", { required: true, maxLength: 200, placeholder: "Mis. Kota Semarang" })}
          <div className="sm:col-span-2">{kolom("alamat", "Alamat", { maxLength: 600 })}</div>
          {kolom("telepon", "Telepon", { maxLength: 60, inputMode: "tel" })}
          {kolom("website", "Website", { maxLength: 400 })}
          {kolom("lat", "Lintang (lat)", { inputMode: "decimal" })}
          {kolom("lng", "Bujur (lng)", { inputMode: "decimal" })}
          <div className="sm:col-span-2">{kolom("jam_buka", "Jam buka", { maxLength: 300 })}</div>
          <div className="sm:col-span-2">{kolom("referensi", "Asal data", { maxLength: 300, placeholder: "Mis. kunjungan sales, 3 Nov" })}</div>
          {kembar && (
            <div role="alert" className="rounded-md bg-review-bg px-3 py-2 text-[12.5px] text-review sm:col-span-2">
              {kembar.pesan}.
              <button type="button" className="ml-1 font-medium underline" onClick={() => onBukaLead(kembar.id)}>
                Buka lead itu
              </button>
            </div>
          )}
          <p className="text-[12px] text-subtle-foreground sm:col-span-2">Lead baru selalu mulai tanpa consent. Menambahkan lead tidak mengirim pesan apa pun.</p>
          <div className="flex justify-end gap-2 sm:col-span-2">
            <AButton type="button" variant="outline" onClick={onClose} disabled={busy}>
              Batal
            </AButton>
            <AButton type="submit" disabled={busy || !isi.nama.trim() || !isi.wilayah.trim()}>
              {busy && <LoaderCircle className="size-4 animate-spin" />} Simpan lead
            </AButton>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
