"use client"

import { CircleCheck, CircleAlert, Download, FileSpreadsheet, LoaderCircle, TriangleAlert, UploadCloud } from "lucide-react"
import Link from "next/link"
import { useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { SkeletonRows } from "@/components/aage/empty-state"
import { GalatMuat, LeadsNav } from "@/components/aage/leads-nav"
import { PageHeader, Panel, Surface } from "@/components/aage/panel"
import { Pill } from "@/components/aage/status"
import { ApiError, api, fetcher, unduh } from "@/lib/api"
import type { LeadImporPratinjau, LeadImporSumber } from "@/lib/types"
import { cn } from "@/lib/utils"

const field = "mt-0.5 h-10 w-full rounded-[10px] border border-line bg-white px-3 text-[14px] outline-none focus:border-brand-500"

function selCsv(nilai: string | number): string {
  const teks = String(nilai)
  const aman = /^[=+\-@\t\r]/.test(teks) ? `'${teks}` : teks
  return `"${aman.replace(/"/g, '""')}"`
}

function unduhLaporanSalah(data: LeadImporPratinjau) {
  const isi = [["baris", "kolom", "alasan"], ...data.laporan.error.map((e) => [e.baris, e.kolom, e.alasan])].map((b) => b.map(selCsv).join(",")).join("\n")
  const url = URL.createObjectURL(new Blob([`﻿${isi}\n`], { type: "text/csv;charset=utf-8" }))
  const a = document.createElement("a")
  a.href = url
  a.download = `baris-salah-${data.nama_file.replace(/\.[^.]+$/, "")}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

function Daftar({ judul, children, jumlah }: { judul: string; jumlah: number; children: React.ReactNode }) {
  if (!jumlah) return null
  return (
    <details className="rounded-lg border border-line bg-white px-3 py-2 text-[13px]">
      <summary className="cursor-pointer font-medium">
        {judul} ({jumlah})
      </summary>
      <ul className="mt-2 max-h-56 space-y-1 overflow-auto text-[12.5px] text-muted-foreground">{children}</ul>
    </details>
  )
}

function Pratinjau({ data, onSelesai, onBatal }: { data: LeadImporPratinjau; onSelesai: (d: LeadImporPratinjau) => void; onBatal: () => void }) {
  const l = data.laporan
  const r = l.ringkasan
  const [lewati, setLewati] = useState(false)
  const [busy, setBusy] = useState(false)
  const akanMasuk = r.baru + r.perlu_tinjauan + r.digabung
  const bisa = akanMasuk > 0 && (r.error === 0 || lewati)

  async function terapkan() {
    setBusy(true)
    try {
      onSelesai(await api<LeadImporPratinjau>(`/api/prospects/impor/${data.token}/terapkan`, { method: "POST", json: { lewati_error: lewati } }))
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Impor gagal. Tidak ada data yang berubah.")
      setBusy(false)
    }
  }

  async function batal() {
    setBusy(true)
    await api(`/api/prospects/impor/${data.token}/batal`, { method: "POST" }).catch(() => undefined)
    onBatal()
  }

  return (
    <Panel className="space-y-4 p-5">
      <div className="flex items-start gap-3">
        <FileSpreadsheet className="mt-0.5 size-5 text-forest-700" aria-hidden />
        <div className="min-w-0">
          <div className="font-semibold">Pratinjau: {data.nama_file}</div>
          <div className="text-[12.5px] text-muted-foreground">Belum ada lead yang masuk. Sumber: {data.source_reference}.</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Pill>{r.baris} baris dibaca</Pill>
        <Pill className="bg-ok-bg text-ok">{r.baru} lead baru</Pill>
        {r.digabung > 0 && <Pill>{r.digabung} digabung ke lead lama</Pill>}
        {r.perlu_tinjauan > 0 && <Pill className="bg-review-bg text-review">{r.perlu_tinjauan} masuk antrean tinjauan</Pill>}
        {r.kembar_file > 0 && <Pill>{r.kembar_file} kembar dalam file</Pill>}
        {r.error > 0 && <Pill className="bg-blocked-bg text-blocked">{r.error} baris salah</Pill>}
      </div>

      {l.peringatan.map((p) => (
        <div key={p} className="flex items-start gap-2 rounded-md bg-review-bg px-3 py-2 text-[12.5px] text-review">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {p}
        </div>
      ))}

      {l.error.length > 0 && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-[13px] font-medium text-blocked">
              <CircleAlert className="size-4" aria-hidden /> Baris berikut tidak akan diimpor
            </div>
            <AButton size="sm" variant="outline" onClick={() => unduhLaporanSalah(data)}>
              <Download className="size-3.5" /> Unduh laporan
            </AButton>
          </div>
          <div className="max-h-72 overflow-auto rounded-lg border border-line">
            <table className="w-full text-[12.5px]">
              <thead className="sticky top-0 bg-soft text-left text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Baris</th>
                  <th className="px-3 py-2 font-medium">Kolom</th>
                  <th className="px-3 py-2 font-medium">Alasan</th>
                </tr>
              </thead>
              <tbody>
                {l.error.map((e, i) => (
                  <tr key={i} className="border-t border-line align-top">
                    <td className="tabular px-3 py-1.5">{e.baris}</td>
                    <td className="px-3 py-1.5 font-mono">{e.kolom}</td>
                    <td className="px-3 py-1.5 text-blocked">{e.alasan}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="grid gap-2 md:grid-cols-3">
        <Daftar judul="Digabung ke lead lama" jumlah={l.digabung.length}>
          {l.digabung.map((d) => (
            <li key={d.baris}>Baris {d.baris}: {d.nama} sama dengan {d.cocok_dengan}. {d.alasan.join("; ")}</li>
          ))}
        </Daftar>
        <Daftar judul="Masuk antrean tinjauan" jumlah={l.perlu_tinjauan.length}>
          {l.perlu_tinjauan.map((d) => (
            <li key={d.baris}>Baris {d.baris}: {d.nama} mirip {d.cocok_dengan.join(", ")}. {d.alasan.join("; ")}</li>
          ))}
        </Daftar>
        <Daftar judul="Kembar dalam file" jumlah={l.kembar_file.length}>
          {l.kembar_file.map((d) => (
            <li key={d.baris}>Baris {d.baris}: {d.nama} sama dengan baris {d.sama_dengan_baris}</li>
          ))}
        </Daftar>
      </div>

      {l.contoh.length > 0 && (
        <Surface className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead className="bg-soft text-left text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Baris</th>
                <th className="px-3 py-2 font-medium">Nama</th>
                <th className="px-3 py-2 font-medium">Segmen</th>
                <th className="px-3 py-2 font-medium">Alamat</th>
                <th className="px-3 py-2 font-medium">Telepon</th>
              </tr>
            </thead>
            <tbody>
              {l.contoh.map((c) => (
                <tr key={c.baris} className="border-t border-line">
                  <td className="tabular px-3 py-1.5">{c.baris}</td>
                  <td className="px-3 py-1.5 font-medium">{c.nama}</td>
                  <td className="px-3 py-1.5">{c.tipe}</td>
                  <td className="px-3 py-1.5">{c.alamat || <span className="text-review">kosong</span>}</td>
                  <td className="px-3 py-1.5">{c.ada_telepon ? "Ada" : <span className="text-review">kosong</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Surface>
      )}

      <p className="text-[12.5px] text-muted-foreground">Lead baru masuk tanpa consent. Consent lead lama tidak berubah, dan impor tidak mengirim pesan apa pun.</p>
      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        {r.error > 0 && akanMasuk > 0 && (
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" checked={lewati} onChange={(e) => setLewati(e.target.checked)} className="size-4" />
            Lewati {r.error} baris salah dan impor sisanya
          </label>
        )}
        <div className="ml-auto flex gap-2">
          <AButton variant="outline" onClick={batal} disabled={busy}>
            Batal
          </AButton>
          <AButton onClick={terapkan} disabled={!bisa || busy}>
            {busy && <LoaderCircle className="size-4 animate-spin" />} Konfirmasi impor
          </AButton>
        </div>
      </div>
    </Panel>
  )
}

export default function ImporLeadPage() {
  const { data: opsi, error, mutate } = useSWR<LeadImporSumber>("/api/prospects/impor/sumber", fetcher, { shouldRetryOnError: false })
  const fileInput = useRef<HTMLInputElement>(null)
  const [sumber, setSumber] = useState("")
  const [referensi, setReferensi] = useState("")
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [galat, setGalat] = useState<string | null>(null)
  const [pratinjau, setPratinjau] = useState<LeadImporPratinjau | null>(null)
  const [selesai, setSelesai] = useState<LeadImporPratinjau | null>(null)
  const siap = Boolean(sumber) && referensi.trim().length >= 3

  async function kirim(f: File) {
    if (!siap) {
      setGalat("Pilih jenis sumber dan isi keterangan sumber dulu.")
      return
    }
    setBusy(true)
    setGalat(null)
    setSelesai(null)
    try {
      const form = new FormData()
      form.append("file", f)
      form.append("source_type", sumber)
      form.append("source_reference", referensi.trim())
      setPratinjau(await api<LeadImporPratinjau>("/api/prospects/impor", { method: "POST", body: form }))
    } catch (err) {
      setGalat(err instanceof Error ? err.message : "File tidak bisa dibaca")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Impor lead" description="Unggah daftar dari sumber yang sah. Datanya diperiksa lebih dulu dan baru masuk setelah Anda konfirmasi." />
      <LeadsNav />
      {error ? (
        <GalatMuat error={error} onUlang={() => mutate()} />
      ) : !opsi ? (
        <SkeletonRows rows={4} />
      ) : pratinjau ? (
        <Pratinjau
          data={pratinjau}
          onBatal={() => setPratinjau(null)}
          onSelesai={(d) => {
            setPratinjau(null)
            setSelesai(d)
            setReferensi("")
          }}
        />
      ) : (
        <>
          {selesai?.hasil && (
            <div role="status" className="flex flex-wrap items-center gap-2 rounded-[12px] border border-ok/30 bg-ok-bg px-4 py-3 text-[13px] text-ok">
              <CircleCheck className="size-4 shrink-0" aria-hidden />
              <span>
                {selesai.nama_file}: {selesai.hasil.baru} lead baru, {selesai.hasil.digabung} digabung, {selesai.hasil.perlu_tinjauan} perlu ditinjau
                {selesai.hasil.dilewati_salah > 0 && `, ${selesai.hasil.dilewati_salah} baris salah dilewati`}.
              </span>
              <span className="ml-auto flex gap-3 font-medium">
                <Link href="/leads" className="underline">Lihat daftar</Link>
                {selesai.hasil.perlu_tinjauan > 0 && <Link href="/leads/tinjauan" className="underline">Buka antrean</Link>}
              </span>
            </div>
          )}
          <Panel className="space-y-4 p-5">
            <div className="grid gap-3 md:grid-cols-2">
              <label className="text-[12px] text-muted-foreground">
                Jenis sumber
                <select value={sumber} onChange={(e) => setSumber(e.target.value)} className={field}>
                  <option value="">Pilih sumber</option>
                  {Object.entries(opsi.sumber).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </label>
              <label className="text-[12px] text-muted-foreground">
                Keterangan sumber
                <input value={referensi} onChange={(e) => setReferensi(e.target.value)} maxLength={300} className={field} placeholder="Mis. daftar toko dari CV Arba'in, November 2026" />
              </label>
            </div>
            <button
              type="button"
              onClick={() => (siap ? fileInput.current?.click() : setGalat("Pilih jenis sumber dan isi keterangan sumber dulu."))}
              onDragOver={(e) => {
                e.preventDefault()
                setOver(true)
              }}
              onDragLeave={() => setOver(false)}
              onDrop={(e) => {
                e.preventDefault()
                setOver(false)
                const f = e.dataTransfer.files?.[0]
                if (f) kirim(f)
              }}
              disabled={busy}
              className={cn(
                "flex w-full flex-col items-center justify-center gap-2 rounded-[14px] border-2 border-dashed border-brand-200 bg-white p-6 text-center transition-colors hover:border-brand-400 hover:bg-brand-50",
                over && "!border-brand-500 bg-brand-50",
                !siap && "opacity-70",
              )}
            >
              {busy ? <LoaderCircle className="size-6 animate-spin text-forest-700" /> : <UploadCloud className="size-6 text-forest-700" />}
              <span className="font-medium">Unggah daftar lead (Excel/CSV)</span>
              <span className="text-[12px] text-muted-foreground">
                .xlsx atau .csv, maksimal {opsi.maks_baris.toLocaleString("id-ID")} baris. Kolom wajib: {opsi.kolom_wajib.join(", ")}.
              </span>
            </button>
            <input
              ref={fileInput}
              type="file"
              accept=".xlsx,.csv"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) kirim(f)
                e.target.value = ""
              }}
            />
            {galat && (
              <div role="alert" className="flex items-start gap-2 rounded-md bg-blocked-bg px-3 py-2 text-[13px] text-blocked">
                <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {galat}
              </div>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-[12px] text-subtle-foreground">Hasil scraping dan daftar kontak yang dibeli tidak boleh diimpor. Kolom consent di file diabaikan.</p>
              <AButton
                size="sm"
                variant="outline"
                onClick={() => unduh("/api/prospects/impor/template.csv", "template_impor_leads.csv").catch((err) => toast.error(err instanceof Error ? err.message : "Unduhan gagal"))}
              >
                <Download className="size-3.5" /> Template CSV
              </AButton>
            </div>
          </Panel>
        </>
      )}
    </div>
  )
}
