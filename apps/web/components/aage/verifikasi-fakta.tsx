"use client"

import { BadgeCheck, LoaderCircle } from "lucide-react"
import { useMemo, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { SkeletonRows } from "@/components/aage/empty-state"
import { Surface } from "@/components/aage/panel"
import { Pill } from "@/components/aage/status"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { api, fetcher, getUser } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import { normalizeRole } from "@/lib/rbac"
import type { FaktaVerifikasi, StatusVerifikasi, VerifikasiDaftar } from "@/lib/types"
import { cn } from "@/lib/utils"

const LABEL: Record<StatusVerifikasi, string> = {
  terverifikasi: "Terverifikasi",
  simulasi: "Simulasi",
  belum_diverifikasi: "Belum diverifikasi",
  kedaluwarsa: "Kedaluwarsa",
}
const WARNA: Record<StatusVerifikasi, string> = {
  terverifikasi: "bg-ok-bg text-ok",
  simulasi: "bg-review-bg text-review",
  belum_diverifikasi: "bg-soft text-muted-foreground",
  kedaluwarsa: "bg-blocked-bg text-blocked",
}
const FILTER: { nilai: StatusVerifikasi | "semua"; label: string }[] = [
  { nilai: "semua", label: "Semua" },
  { nilai: "belum_diverifikasi", label: "Belum terverifikasi" },
  { nilai: "kedaluwarsa", label: "Kedaluwarsa" },
  { nilai: "simulasi", label: "Simulasi" },
  { nilai: "terverifikasi", label: "Terverifikasi" },
]
const PER_HALAMAN = 50

export function StatusFakta({ status }: { status: StatusVerifikasi }) {
  return <Pill className={WARNA[status]}>{LABEL[status]}</Pill>
}

function DialogStatus({ fakta, onTutup, onTersimpan }: { fakta: FaktaVerifikasi; onTutup: () => void; onTersimpan: () => void }) {
  const [status, setStatus] = useState<StatusVerifikasi>("terverifikasi")
  const [bukti, setBukti] = useState(fakta.sumber_bukti ?? "")
  const [berlaku, setBerlaku] = useState(fakta.berlaku_sampai ?? "")
  const [busy, setBusy] = useState(false)
  const wajibBukti = status === "terverifikasi"
  const nama = getUser()?.nama

  async function simpan() {
    setBusy(true)
    try {
      await api("/api/kb/verifikasi", {
        method: "PUT",
        json: {
          objek_tipe: fakta.objek_tipe,
          objek_id: fakta.objek_id,
          jenis_fakta: fakta.jenis_fakta,
          status,
          sumber_bukti: bukti.trim() || null,
          berlaku_sampai: berlaku || null,
        },
      })
      toast.success("Status tersimpan dan tercatat di Ledger")
      onTersimpan()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Gagal menyimpan status")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && onTutup()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ubah status fakta</DialogTitle>
          <DialogDescription>
            {fakta.produk ? `${fakta.produk.nama} · ` : ""}
            {fakta.label}
          </DialogDescription>
        </DialogHeader>
        <p className="rounded-lg border border-line bg-soft p-3 text-[13px] break-words">{fakta.nilai}</p>
        <label className="block text-[13px] font-medium">
          Status
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as StatusVerifikasi)}
            className="mt-1 h-10 w-full rounded-md border border-line bg-card px-3 font-normal outline-none focus:border-brand-500"
          >
            {(Object.keys(LABEL) as StatusVerifikasi[]).map((s) => (
              <option key={s} value={s}>
                {LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-[13px] font-medium">
          Sumber bukti{wajibBukti ? " (wajib)" : ""}
          <Input
            value={bukti}
            onChange={(e) => setBukti(e.target.value)}
            placeholder="Mis. Sertifikat BPOM yang diterima 12/11/2026"
            maxLength={500}
            className="mt-1 font-normal"
          />
        </label>
        <label className="block text-[13px] font-medium">
          Berlaku sampai (opsional)
          <Input type="date" value={berlaku} onChange={(e) => setBerlaku(e.target.value)} className="mt-1 font-normal" />
        </label>
        <p className="text-[12px] text-muted-foreground">
          Dicatat atas nama akun yang login{nama ? ` (${nama})` : ""}. Bila nilainya berubah sesudah ini, verifikasinya batal otomatis.
        </p>
        <DialogFooter>
          <AButton variant="outline" onClick={onTutup} disabled={busy}>
            Batal
          </AButton>
          <AButton onClick={simpan} disabled={busy || (wajibBukti && bukti.trim().length < 3)}>
            {busy ? <LoaderCircle className="size-4 animate-spin" /> : <BadgeCheck className="size-4" />} Simpan
          </AButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function VerifikasiFakta({ onBerubah }: { onBerubah?: () => void }) {
  const { data, mutate } = useSWR<VerifikasiDaftar>("/api/kb/verifikasi", fetcher)
  const [filter, setFilter] = useState<StatusVerifikasi | "semua">("semua")
  const [cari, setCari] = useState("")
  const [batas, setBatas] = useState(PER_HALAMAN)
  const [dipilih, setDipilih] = useState<FaktaVerifikasi | null>(null)
  const isAdmin = normalizeRole(getUser()?.role) === "admin"

  const tampil = useMemo(() => {
    const q = cari.trim().toLowerCase()
    return (data?.items ?? []).filter(
      (f) =>
        (filter === "semua" || f.status === filter) &&
        (!q || `${f.produk?.nama ?? ""} ${f.produk?.sku ?? ""} ${f.label} ${f.nilai}`.toLowerCase().includes(q)),
    )
  }, [data, filter, cari])

  if (!data) return <SkeletonRows rows={8} />
  const total = data.items.length

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        {FILTER.map((f) => {
          const jumlah = f.nilai === "semua" ? total : data.ringkasan[f.nilai]
          return (
            <button
              key={f.nilai}
              type="button"
              aria-pressed={filter === f.nilai}
              onClick={() => {
                setFilter(f.nilai)
                setBatas(PER_HALAMAN)
              }}
              className={cn(
                "h-8 rounded-full border border-line px-3 text-[12px] font-medium text-muted-foreground hover:bg-soft",
                filter === f.nilai && "border-forest-700 bg-forest-700 text-white hover:bg-forest-700",
              )}
            >
              {f.label} ({jumlah})
            </button>
          )
        })}
        <Input value={cari} onChange={(e) => setCari(e.target.value)} placeholder="Cari produk atau fakta" className="ml-auto h-8 w-full sm:w-56" />
      </div>
      <p className="text-[12px] text-muted-foreground">
        Mode data aktif: <b className="font-medium text-foreground">{data.mode_data}</b>. AI hanya mengutip fakta terverifikasi yang masih berlaku
        {data.mode_data === "demo" ? "; fakta simulasi dikutip dengan label data contoh." : "."}
      </p>
      <Surface className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead className="bg-soft text-left text-[12px] tracking-[0.02em] text-muted-foreground">
            <tr>
              <th className="px-3 py-2.5 font-medium">Produk / dokumen</th>
              <th className="px-3 py-2.5 font-medium">Fakta</th>
              <th className="px-3 py-2.5 font-medium">Nilai</th>
              <th className="px-3 py-2.5 font-medium">Status</th>
              <th className="px-3 py-2.5 font-medium">Bukti</th>
              {isAdmin && <th className="px-3 py-2.5 font-medium" aria-label="Tindakan" />}
            </tr>
          </thead>
          <tbody>
            {tampil.slice(0, batas).map((f) => (
              <tr key={`${f.objek_tipe}-${f.objek_id}-${f.jenis_fakta}`} className="border-t border-line align-top">
                <td className="px-3 py-2.5">
                  {f.produk ? (
                    <>
                      <div className="font-medium">{f.produk.nama}</div>
                      <div className="font-mono text-[12px] text-muted-foreground">{f.produk.sku}</div>
                    </>
                  ) : (
                    <span className="font-medium">Dokumen</span>
                  )}
                </td>
                <td className="px-3 py-2.5 whitespace-nowrap">{f.label}</td>
                <td className="max-w-[320px] px-3 py-2.5 break-words text-muted-foreground">{f.nilai}</td>
                <td className="px-3 py-2.5 whitespace-nowrap">
                  <StatusFakta status={f.status} />
                  {f.nilai_berubah && <div className="mt-1 text-[12px] text-review">Nilai berubah sesudah diverifikasi</div>}
                  {f.berlaku_sampai && <div className="mt-1 text-[12px] text-muted-foreground">s.d. {f.berlaku_sampai}</div>}
                </td>
                <td className="max-w-[240px] px-3 py-2.5 text-[12px] break-words text-muted-foreground">
                  {f.sumber_bukti ?? "–"}
                  {f.diverifikasi_oleh && (
                    <div className="mt-1">
                      {f.diverifikasi_oleh}
                      {f.diverifikasi_pada ? `, ${formatDateTime(f.diverifikasi_pada)}` : ""}
                    </div>
                  )}
                </td>
                {isAdmin && (
                  <td className="px-3 py-2.5 text-right">
                    <AButton size="sm" variant="outline" onClick={() => setDipilih(f)}>
                      Ubah status
                    </AButton>
                  </td>
                )}
              </tr>
            ))}
            {tampil.length === 0 && (
              <tr>
                <td colSpan={isAdmin ? 6 : 5} className="px-3 py-8 text-center text-muted-foreground">
                  Tidak ada fakta dengan filter ini.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Surface>
      {tampil.length > batas && (
        <AButton variant="outline" size="sm" onClick={() => setBatas((b) => b + PER_HALAMAN)}>
          Tampilkan lebih banyak ({tampil.length - batas} lagi)
        </AButton>
      )}
      {!isAdmin && <p className="text-[12px] text-muted-foreground">Hanya Admin yang dapat mengubah status.</p>}
      {dipilih && (
        <DialogStatus
          key={`${dipilih.objek_tipe}-${dipilih.objek_id}-${dipilih.jenis_fakta}`}
          fakta={dipilih}
          onTutup={() => setDipilih(null)}
          onTersimpan={() => {
            setDipilih(null)
            mutate()
            onBerubah?.()
          }}
        />
      )}
    </div>
  )
}
