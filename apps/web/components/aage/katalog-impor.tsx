"use client"

import { CircleAlert, Download, FileSpreadsheet, LoaderCircle, TriangleAlert, UploadCloud, X } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"

import { AButton } from "@/components/aage/button"
import { Panel, Surface } from "@/components/aage/panel"
import { Pill } from "@/components/aage/status"
import { api, unduh } from "@/lib/api"
import { formatRp } from "@/lib/format"
import type { KatalogMasalah, KatalogPratinjau } from "@/lib/types"
import { cn } from "@/lib/utils"

const UNDUHAN = [
  { label: "Template Excel", path: "/api/katalog/template.xlsx", file: "template_katalog_aage.xlsx" },
  { label: "Template CSV produk", path: "/api/katalog/template.csv", file: "template_katalog_produk.csv" },
  { label: "Template CSV kebijakan", path: "/api/katalog/template-kebijakan.csv", file: "template_katalog_kebijakan.csv" },
  { label: "Ekspor katalog aktif", path: "/api/katalog/ekspor.xlsx", file: "katalog_aktif_aage.xlsx" },
]

function MasalahTabel({ items, tone }: { items: KatalogMasalah[]; tone: "error" | "warn" }) {
  return (
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
          {items.map((m, i) => (
            <tr key={i} className="border-t border-line align-top">
              <td className="tabular px-3 py-1.5 whitespace-nowrap">
                {m.sheet ? `${m.sheet} · ` : ""}
                {m.baris}
              </td>
              <td className="px-3 py-1.5 font-mono whitespace-nowrap">{m.kolom}</td>
              <td className={cn("px-3 py-1.5", tone === "error" ? "text-blocked" : "text-review")}>{m.alasan}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Daftar({ judul, items }: { judul: string; items: string[] }) {
  if (!items.length) return null
  return (
    <details className="rounded-lg border border-line bg-white px-3 py-2 text-[13px]">
      <summary className="cursor-pointer font-medium">
        {judul} ({items.length})
      </summary>
      <ul className="mt-2 max-h-48 list-disc space-y-0.5 overflow-auto pl-5 text-muted-foreground">
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </details>
  )
}

function Pratinjau({ data, onSelesai, onBatal }: { data: KatalogPratinjau; onSelesai: () => void; onBatal: () => void }) {
  const r = data.laporan.ringkasan
  const [lewati, setLewati] = useState(false)
  const [busy, setBusy] = useState(false)
  const adaError = data.laporan.error.length > 0
  const bisa = r.valid > 0 && (!adaError || lewati)

  async function terapkan() {
    setBusy(true)
    try {
      const h = await api<{ versi: number; produk: number; dinonaktifkan: number; kebijakan_versi: number | null }>(
        `/api/katalog/impor/${data.token}/terapkan`,
        { method: "POST", json: { lewati_error: lewati } },
      )
      toast.success(
        `Katalog v${h.versi} aktif: ${h.produk} produk` +
          (h.dinonaktifkan ? `, ${h.dinonaktifkan} dinonaktifkan` : "") +
          (h.kebijakan_versi ? ", kebijakan diganti" : ""),
      )
      onSelesai()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Gagal menerapkan katalog")
    } finally {
      setBusy(false)
    }
  }

  async function batal() {
    await api(`/api/katalog/impor/${data.token}/batal`, { method: "POST" }).catch(() => undefined)
    onBatal()
  }

  return (
    <Panel className="space-y-4 p-5">
      <div className="flex flex-wrap items-start gap-3">
        <FileSpreadsheet className="mt-0.5 size-5 text-forest-700" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="font-semibold">Pratinjau: {data.nama_file}</div>
          <div className="text-[12.5px] text-muted-foreground">
            Katalog belum berubah. Periksa ringkasan di bawah, lalu terapkan atau batalkan.
            {r.status_verifikasi &&
              ` Status baris: ${r.status_verifikasi.simulasi ?? 0} simulasi, ${r.status_verifikasi.belum_diverifikasi ?? 0} belum diverifikasi, ${r.status_verifikasi.kedaluwarsa ?? 0} kedaluwarsa. Impor tidak menandai data terverifikasi; admin memverifikasinya di tab Verifikasi.`}
          </div>
        </div>
        <AButton size="icon" variant="ghost" onClick={batal} aria-label="Batalkan pratinjau">
          <X className="size-4" />
        </AButton>
      </div>

      <div className="flex flex-wrap gap-1.5">
        <Pill className="bg-ok-bg text-ok">{r.valid} baris valid</Pill>
        {r.error > 0 && <Pill className="bg-blocked-bg text-blocked">{r.error} baris error</Pill>}
        <Pill>{r.baru} baru</Pill>
        <Pill>{r.diubah} diubah</Pill>
        <Pill>{r.tetap} tetap</Pill>
        {r.dinonaktifkan > 0 && <Pill className="bg-review-bg text-review">{r.dinonaktifkan} dinonaktifkan</Pill>}
        <Pill>
          {r.kebijakan === null
            ? "Kebijakan tidak diubah"
            : data.laporan.ganti_kebijakan
              ? `${r.kebijakan} topik kebijakan diganti`
              : "Kebijakan tidak diganti (ada error)"}
        </Pill>
      </div>

      {adaError && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-[13px] font-medium text-blocked">
            <CircleAlert className="size-4" aria-hidden /> Baris berikut tidak akan diimpor
          </div>
          <MasalahTabel items={data.laporan.error} tone="error" />
        </div>
      )}

      {data.laporan.jumlah_peringatan > 0 && (
        <details>
          <summary className="flex cursor-pointer items-center gap-2 text-[13px] font-medium text-review">
            <TriangleAlert className="size-4" aria-hidden /> {data.laporan.jumlah_peringatan} peringatan (tetap diimpor;
            data kosong dijawab AI &quot;belum ada datanya&quot;)
          </summary>
          <div className="mt-2">
            <MasalahTabel items={data.laporan.peringatan} tone="warn" />
          </div>
        </details>
      )}

      <div className="grid gap-2 md:grid-cols-3">
        <Daftar judul="Produk baru" items={data.laporan.baru} />
        <Daftar judul="Produk diubah" items={data.laporan.diubah.map((d) => `${d.nama}: ${d.perubahan.join(", ")}`)} />
        <Daftar judul="Akan dinonaktifkan" items={data.laporan.dinonaktifkan} />
      </div>

      {data.laporan.contoh.length > 0 && (
        <Surface className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead className="bg-soft text-left text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Baris</th>
                <th className="px-3 py-2 font-medium">Produk</th>
                <th className="px-3 py-2 text-right font-medium">Harga</th>
                <th className="px-3 py-2 text-right font-medium">MOQ</th>
                <th className="px-3 py-2 text-right font-medium">Stok</th>
                <th className="px-3 py-2 font-medium">Izin edar</th>
                <th className="px-3 py-2 font-medium">Halal</th>
                <th className="px-3 py-2 font-medium">BKO</th>
              </tr>
            </thead>
            <tbody>
              {data.laporan.contoh.map((c) => (
                <tr key={c.baris} className="border-t border-line">
                  <td className="tabular px-3 py-1.5">{c.baris}</td>
                  <td className="px-3 py-1.5 font-medium">{c.nama}</td>
                  <td className="tabular px-3 py-1.5 text-right whitespace-nowrap">{formatRp(c.harga_dasar)}</td>
                  <td className="tabular px-3 py-1.5 text-right">{c.moq}</td>
                  <td className="tabular px-3 py-1.5 text-right">{c.stok ?? <span className="text-subtle-foreground">–</span>}</td>
                  <td className="px-3 py-1.5 font-mono">{c.no_izin_edar || <span className="text-review">belum ada</span>}</td>
                  <td className="px-3 py-1.5">{c.halal || <span className="text-review">belum ada</span>}</td>
                  <td className="px-3 py-1.5">{c.bko || <span className="text-review">belum ada</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {r.valid > data.laporan.contoh.length && (
            <div className="border-t border-line px-3 py-2 text-[12px] text-muted-foreground">
              Menampilkan {data.laporan.contoh.length} dari {r.valid} baris valid.
            </div>
          )}
        </Surface>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        {adaError && r.valid > 0 && (
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" checked={lewati} onChange={(e) => setLewati(e.target.checked)} className="size-4" />
            Lewati {r.error} baris error dan impor {r.valid} baris valid
          </label>
        )}
        <div className="ml-auto flex gap-2">
          <AButton variant="outline" onClick={batal} disabled={busy}>
            Batal
          </AButton>
          <AButton onClick={terapkan} disabled={!bisa || busy}>
            {busy && <LoaderCircle className="size-4 animate-spin" />} Terapkan katalog
          </AButton>
        </div>
      </div>
    </Panel>
  )
}

export function KatalogImpor({ onSelesai }: { onSelesai: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const [pratinjau, setPratinjau] = useState<KatalogPratinjau | null>(null)

  async function kirim(f: File) {
    setBusy(true)
    try {
      const form = new FormData()
      form.append("file", f)
      setPratinjau(await api<KatalogPratinjau>("/api/katalog/impor", { method: "POST", body: form }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "File tidak bisa dibaca")
    } finally {
      setBusy(false)
    }
  }

  if (pratinjau) {
    return (
      <Pratinjau
        data={pratinjau}
        onBatal={() => setPratinjau(null)}
        onSelesai={() => {
          setPratinjau(null)
          onSelesai()
        }}
      />
    )
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => input.current?.click()}
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
        )}
      >
        {busy ? <LoaderCircle className="size-6 animate-spin text-forest-700" /> : <UploadCloud className="size-6 text-forest-700" />}
        <span className="font-medium">Unggah katalog mitra (Excel/CSV)</span>
        <span className="text-[12px] text-muted-foreground">
          Seret file ke sini atau klik · .xlsx / .csv · pratinjau dulu, katalog baru diganti setelah Anda konfirmasi
        </span>
        <input
          ref={input}
          type="file"
          accept=".xlsx,.csv"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) kirim(f)
            e.target.value = ""
          }}
        />
      </button>
      <div className="flex flex-wrap gap-2">
        {UNDUHAN.map((u) => (
          <AButton
            key={u.path}
            size="sm"
            variant="outline"
            onClick={() => unduh(u.path, u.file).catch((err) => toast.error(err instanceof Error ? err.message : "Unduhan gagal"))}
          >
            <Download className="size-3.5" /> {u.label}
          </AButton>
        ))}
      </div>
    </div>
  )
}
