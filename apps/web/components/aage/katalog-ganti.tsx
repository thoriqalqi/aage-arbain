"use client"

import { Archive, CheckCircle2, CircleAlert, Database, FileSpreadsheet, LoaderCircle, ShieldCheck, Trash2, TriangleAlert, X } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { RincianPratinjau, UnggahKatalog } from "@/components/aage/katalog-impor"
import { Panel } from "@/components/aage/panel"
import { Pill } from "@/components/aage/status"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { api, fetcher } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import type { KatalogGantiDampak, KatalogGantiHasil, KatalogGantiRingkasan, KatalogGantiStatus, KatalogPratinjau, ModeGantiKatalog } from "@/lib/types"
import { cn } from "@/lib/utils"

const PANTAU_MS = 2000

function Angka({ label, nilai }: { label: string; nilai: number }) {
  return (
    <div className="rounded-lg border border-line bg-white px-3 py-2">
      <div className="tabular text-[17px] font-semibold">{nilai.toLocaleString("id-ID")}</div>
      <div className="text-[12px] text-muted-foreground">{label}</div>
    </div>
  )
}

function KatalogSekarang({ info }: { info: KatalogGantiRingkasan }) {
  const s = info.sekarang
  const online = info.sumber.jenis === "online"
  return (
    <Panel className="space-y-3 p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Database className="size-4 text-forest-700" aria-hidden />
        <div className="font-semibold">Katalog yang dipakai agent sekarang</div>
        {s.tampak_demo && <Pill className="bg-review-bg text-review">Data demo</Pill>}
        <Pill className={info.mode_data === "demo" ? "bg-review-bg text-review" : "bg-ok-bg text-ok"}>Mode {info.mode_data}</Pill>
        <Pill className={online ? "bg-ok-bg text-ok" : "bg-blocked-bg text-blocked"}>
          {online ? `Supabase · ${info.sumber.host}` : `Database lokal, bukan Supabase · ${info.sumber.host ?? info.sumber.nama}`}
        </Pill>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Angka label="Produk aktif" nilai={s.produk} />
        <Angka label="Klaim" nilai={s.klaim} />
        <Angka label="Tier harga" nilai={s.tier} />
        <Angka label="Potongan pencarian" nilai={s.chunk} />
      </div>
      {info.terakhir_diganti && (
        <p className="text-[12.5px] text-muted-foreground">
          Terakhir diganti {formatDateTime(info.terakhir_diganti.pada)} ({info.terakhir_diganti.mode === "hapus" ? "hapus permanen" : "dinonaktifkan"}).
        </p>
      )}
    </Panel>
  )
}

function CatatanDampak({ dampak, statusBaris, modeData }: { dampak: KatalogGantiDampak; statusBaris?: KatalogPratinjau["laporan"]["ringkasan"]["status_verifikasi"]; modeData: string }) {
  const catatan: string[] = []
  const belum = statusBaris?.belum_diverifikasi ?? 0
  const simulasi = statusBaris?.simulasi ?? 0
  if (belum > 0) catatan.push(`${belum} baris belum diverifikasi: agent belum mengutip faktanya sampai admin memverifikasi di tab Verifikasi.`)
  if (simulasi > 0 && modeData === "produksi") catatan.push(`${simulasi} baris berstatus simulasi: di mode produksi agent menahannya. Untuk menampilkannya, pakai mode demo di Pengaturan.`)
  if (dampak.kebijakan === "hilang") catatan.push("File ini tidak membawa kebijakan. Kebijakan demo ikut disingkirkan, jadi agent menjawab belum ada datanya dan menawarkan staf.")
  if (dampak.kebijakan === "tetap") catatan.push("File ini tidak membawa kebijakan. Kebijakan yang aktif sekarang tetap dipakai.")
  if (dampak.draf_menunggu > 0) catatan.push(`${dampak.draf_menunggu} draf approval yang menunggu dibuat dari katalog lama. Sesudah diganti, draf itu tidak bisa disetujui apa adanya; tolak atau tulis ulang.`)
  if (dampak.produk_terkunci.length > 0) catatan.push(`${dampak.produk_terkunci.length} produk dirujuk draf pemasaran atau audit, jadi barisnya tetap ada dalam keadaan nonaktif walau memilih hapus permanen.`)
  if (!catatan.length) return null
  return (
    <div className="space-y-1.5 rounded-lg border border-review/30 bg-review-bg p-3 text-[13px]">
      {catatan.map((c) => (
        <div key={c} className="flex gap-2">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-review" aria-hidden />
          <span>{c}</span>
        </div>
      ))}
    </div>
  )
}

function Dampak({ info }: { info: KatalogGantiRingkasan }) {
  const d = info.dampak
  if (!d) return <div className="h-24 animate-pulse rounded-lg bg-soft" />
  const t = info.tidak_disentuh
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <div className="rounded-lg border border-line bg-white p-3">
        <div className="mb-2 text-[13px] font-semibold">Disingkirkan dari katalog lama</div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Angka label="Produk" nilai={d.produk} />
          <Angka label="Klaim" nilai={d.klaim} />
          <Angka label="Tier harga" nilai={d.tier} />
          <Angka label="Potongan + vektor" nilai={d.chunk} />
          <Angka label="Baris verifikasi" nilai={d.verifikasi} />
          <Angka label="Dokumen" nilai={d.dokumen.length} />
        </div>
        {d.dokumen.length > 0 && <p className="mt-2 text-[12.5px] text-muted-foreground">Dokumen: {d.dokumen.join("; ")}</p>}
      </div>
      <div className="rounded-lg border border-line bg-white p-3">
        <div className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold">
          <ShieldCheck className="size-4 text-ok" aria-hidden /> Tidak disentuh
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Angka label="Ledger" nilai={t.ledger} />
          <Angka label="Percakapan" nilai={t.percakapan} />
          <Angka label="Pesan" nilai={t.pesan} />
          <Angka label="Kontak" nilai={t.kontak} />
        </div>
        <p className="mt-2 text-[12.5px] text-muted-foreground">
          Ledger hanya bertambah catatan penggantian.
          {d.dokumen_tetap.length > 0 && ` Dokumen staf yang tetap dipakai: ${d.dokumen_tetap.join("; ")}.`}
        </p>
      </div>
    </div>
  )
}

function PilihMode({ mode, onChange }: { mode: ModeGantiKatalog; onChange: (m: ModeGantiKatalog) => void }) {
  const pilihan = [
    {
      nilai: "nonaktif" as const,
      judul: "Nonaktifkan (disarankan)",
      ikon: Archive,
      isi: "Data lama disimpan tetapi tidak lagi dibaca agent. Bisa dikembalikan dengan mengunggah file katalog lama.",
    },
    {
      nilai: "hapus" as const,
      judul: "Hapus permanen",
      ikon: Trash2,
      isi: "Produk, klaim, tier, potongan beserta vektor, dokumen, dan baris verifikasi lama dihapus. Tidak bisa dibatalkan.",
    },
  ]
  return (
    <div role="radiogroup" aria-label="Cara menyingkirkan katalog lama" className="grid gap-2 md:grid-cols-2">
      {pilihan.map((p) => (
        <label
          key={p.nilai}
          className={cn(
            "flex cursor-pointer gap-3 rounded-lg border bg-white p-3 transition-colors",
            mode === p.nilai ? "border-brand-500 bg-brand-50" : "border-line hover:border-brand-200",
          )}
        >
          <input type="radio" name="mode-ganti" className="mt-1 size-4" checked={mode === p.nilai} onChange={() => onChange(p.nilai)} />
          <span className="min-w-0">
            <span className="flex items-center gap-1.5 text-[13.5px] font-medium">
              <p.ikon className="size-4" aria-hidden /> {p.judul}
            </span>
            <span className="mt-0.5 block text-[12.5px] text-muted-foreground">{p.isi}</span>
          </span>
        </label>
      ))}
    </div>
  )
}

function Konfirmasi({
  info,
  mode,
  jumlahBaru,
  onBatal,
  onYakin,
}: {
  info: KatalogGantiRingkasan
  mode: ModeGantiKatalog
  jumlahBaru: number
  onBatal: () => void
  onYakin: (konfirmasi: string) => void
}) {
  const batal = useRef<HTMLButtonElement>(null)
  const [teks, setTeks] = useState("")
  const hapus = mode === "hapus"
  const d = info.dampak
  const cocok = !hapus || teks.trim() === info.konfirmasi_hapus
  return (
    <Dialog open onOpenChange={(o) => !o && onBatal()}>
      <DialogContent initialFocus={batal}>
        <DialogHeader>
          <DialogTitle>{hapus ? "Hapus permanen katalog lama?" : "Ganti seluruh katalog?"}</DialogTitle>
          <DialogDescription>
            {d?.produk ?? 0} produk lama {hapus ? "dihapus permanen" : "dinonaktifkan"} dan digantikan {jumlahBaru} produk dari file ini. Pesan pembeli berikutnya langsung dijawab dari katalog baru. Ledger, percakapan, dan kontak tidak disentuh.
          </DialogDescription>
        </DialogHeader>
        {hapus && (
          <div className="space-y-2">
            <div className="flex gap-2 rounded-lg border border-blocked/30 bg-blocked-bg p-3 text-[13px] text-blocked">
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
              <span>Tidak bisa dibatalkan. Sebelum lanjut, unduh Ekspor katalog aktif dan buat cadangan database.</span>
            </div>
            <label className="block text-[13px]">
              Ketik <span className="font-mono font-semibold">{info.konfirmasi_hapus}</span> untuk melanjutkan
              <input
                value={teks}
                onChange={(e) => setTeks(e.target.value)}
                autoComplete="off"
                className="mt-1 h-10 w-full rounded-md border border-line bg-white px-3 font-mono outline-none focus:border-brand-500"
              />
            </label>
          </div>
        )}
        <DialogFooter>
          <AButton ref={batal} variant="outline" onClick={onBatal}>
            Batal
          </AButton>
          <AButton variant={hapus ? "destructive" : "default"} disabled={!cocok} onClick={() => onYakin(teks)}>
            {hapus ? "Hapus dan ganti" : "Ya, ganti katalog"}
          </AButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Selesai({ hasil, onTutup }: { hasil: KatalogGantiHasil; onTutup: () => void }) {
  const s = hasil.disingkirkan
  const belum = hasil.status_fakta.belum_diverifikasi ?? 0
  return (
    <Panel className="space-y-3 p-5">
      <div className="flex items-center gap-2 font-semibold text-ok">
        <CheckCircle2 className="size-5" aria-hidden /> Katalog v{hasil.versi} aktif. Agent sudah memakainya, tanpa restart.
      </div>
      <p className="text-[13px] text-muted-foreground">
        {hasil.produk} produk dan {hasil.klaim} klaim baru. Dari katalog lama, {s.produk} produk, {s.klaim} klaim, {s.tier} tier, {s.chunk} potongan, dan {s.verifikasi} baris verifikasi {s.mode === "hapus" ? "dihapus permanen" : "dinonaktifkan"}.
        {s.produk_terkunci > 0 && ` ${s.produk_terkunci} produk tetap ada dalam keadaan nonaktif karena dirujuk draf pemasaran atau audit.`}
      </p>
      {belum > 0 && <p className="text-[13px] text-review">{belum} fakta belum diverifikasi. Agent belum mengutipnya sampai admin memverifikasi di tab Verifikasi.</p>}
      <AButton variant="outline" onClick={onTutup}>
        Selesai
      </AButton>
    </Panel>
  )
}

export function KatalogGanti({ onSelesai }: { onSelesai: () => void }) {
  const [pratinjau, setPratinjau] = useState<KatalogPratinjau | null>(null)
  const [mode, setMode] = useState<ModeGantiKatalog>("nonaktif")
  const [lewati, setLewati] = useState(false)
  const [konfirmasi, setKonfirmasi] = useState(false)
  const [berjalan, setBerjalan] = useState(false)
  const [gagal, setGagal] = useState<string | null>(null)
  const [hasil, setHasil] = useState<KatalogGantiHasil | null>(null)
  const token = pratinjau?.token
  const { data: info, error, mutate } = useSWR<KatalogGantiRingkasan>(`/api/katalog/ganti/ringkasan${token ? `?token=${token}` : ""}`, fetcher)

  useEffect(() => {
    if (!berjalan || !token) return
    let batal = false
    let timer: ReturnType<typeof setTimeout>
    async function pantau() {
      try {
        const st = await api<KatalogGantiStatus>(`/api/katalog/ganti/${token}`)
        if (batal) return
        if (st.status === "diterapkan" && st.hasil) {
          setBerjalan(false)
          setHasil(st.hasil)
          setPratinjau(null)
          toast.success(`Katalog v${st.hasil.versi} aktif`)
          mutate()
          onSelesai()
          return
        }
        if (st.status !== "diproses") {
          setBerjalan(false)
          setGagal(st.gagal ?? "Penggantian tidak selesai. Katalog lama tetap utuh.")
          return
        }
      } catch {
        // Gangguan sesaat saat memantau tidak berarti penggantiannya gagal; coba baca lagi.
      }
      if (!batal) timer = setTimeout(pantau, PANTAU_MS)
    }
    pantau()
    return () => {
      batal = true
      clearTimeout(timer)
    }
  }, [berjalan, token, mutate, onSelesai])

  async function jalankan(teks: string) {
    if (!token) return
    setKonfirmasi(false)
    setGagal(null)
    try {
      await api(`/api/katalog/ganti/${token}`, { method: "POST", json: { mode, konfirmasi: teks, lewati_error: lewati } })
      setBerjalan(true)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Penggantian ditolak")
    }
  }

  async function batalkan() {
    if (token) await api(`/api/katalog/impor/${token}/batal`, { method: "POST" }).catch(() => undefined)
    setPratinjau(null)
    setGagal(null)
    setLewati(false)
    setMode("nonaktif")
  }

  const r = pratinjau?.laporan.ringkasan
  const adaError = (pratinjau?.laporan.error.length ?? 0) > 0
  const bisa = !!r && r.valid > 0 && (!adaError || lewati) && !!info?.dampak

  return (
    <div className="space-y-4">
      {info ? <KatalogSekarang info={info} /> : !error && <div className="panel h-36 animate-pulse" />}
      {error && <Panel className="p-5 text-[13px] text-blocked">Ringkasan katalog tidak bisa dibaca: {error instanceof Error ? error.message : "gangguan koneksi"}</Panel>}

      {hasil && (
        <Selesai
          hasil={hasil}
          onTutup={() => {
            setHasil(null)
            setMode("nonaktif")
            setLewati(false)
          }}
        />
      )}

      {!pratinjau && !hasil && (
        <UnggahKatalog
          label="Unggah katalog pengganti (Excel/CSV)"
          petunjuk="Seret file sesuai template ke sini atau klik · katalog belum berubah sampai Anda menekan Ganti seluruh katalog"
          onPratinjau={setPratinjau}
        />
      )}

      {pratinjau && (
        <Panel className="space-y-4 p-5">
          <div className="flex flex-wrap items-start gap-3">
            <FileSpreadsheet className="mt-0.5 size-5 text-forest-700" aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="font-semibold">Pratinjau: {pratinjau.nama_file}</div>
              <div className="text-[12.5px] text-muted-foreground">Katalog belum berubah. Periksa isi file dan dampaknya, lalu pilih cara menyingkirkan katalog lama.</div>
            </div>
            <AButton size="icon" variant="ghost" onClick={batalkan} disabled={berjalan} aria-label="Batalkan pratinjau">
              <X className="size-4" />
            </AButton>
          </div>

          <RincianPratinjau data={pratinjau} />
          {info && <Dampak info={info} />}
          {info?.dampak && <CatatanDampak dampak={info.dampak} statusBaris={r?.status_verifikasi} modeData={info.mode_data} />}
          <PilihMode mode={mode} onChange={setMode} />

          {gagal && (
            <div className="flex gap-2 rounded-lg border border-blocked/30 bg-blocked-bg p-3 text-[13px] text-blocked" role="alert">
              <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden /> {gagal}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
            {adaError && (r?.valid ?? 0) > 0 && (
              <label className="flex items-center gap-2 text-[13px]">
                <input type="checkbox" checked={lewati} onChange={(e) => setLewati(e.target.checked)} className="size-4" />
                Lewati {r?.error} baris error dan pakai {r?.valid} baris valid
              </label>
            )}
            {berjalan && (
              <span className="flex items-center gap-2 text-[13px] text-muted-foreground" role="status">
                <LoaderCircle className="size-4 animate-spin" aria-hidden /> Sedang mengganti. Agent memakai katalog lama sampai proses selesai.
              </span>
            )}
            <div className="ml-auto flex gap-2">
              <AButton variant="outline" onClick={batalkan} disabled={berjalan}>
                Batal
              </AButton>
              <AButton variant={mode === "hapus" ? "destructive" : "default"} onClick={() => setKonfirmasi(true)} disabled={!bisa || berjalan}>
                {berjalan && <LoaderCircle className="size-4 animate-spin" />} Ganti seluruh katalog
              </AButton>
            </div>
          </div>
        </Panel>
      )}

      {konfirmasi && info && r && <Konfirmasi info={info} mode={mode} jumlahBaru={r.valid} onBatal={() => setKonfirmasi(false)} onYakin={jalankan} />}
    </div>
  )
}
