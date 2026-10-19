"use client"

import { BadgeCheck, FileUp, Link2, LoaderCircle, ShieldCheck, UploadCloud } from "lucide-react"
import { useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { SkeletonRows } from "@/components/aage/empty-state"
import { Panel, PageHeader, Surface } from "@/components/aage/panel"
import { Pill } from "@/components/aage/status"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, fetcher, getUser } from "@/lib/api"
import { formatDateTime, formatRp } from "@/lib/format"
import type { Product } from "@/lib/types"
import { cn } from "@/lib/utils"

type Doc = { id: number; judul: string; tipe: string; url: string | null; versi: number; aktif: boolean; diunggah_pada: string; potongan: number }

function Dropzone({ accept, label, onFile, busy }: { accept: string; label: string; onFile: (f: File) => void; busy: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  return (
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
        if (f) onFile(f)
      }}
      className={cn(
        "flex w-full flex-col items-center justify-center gap-2 rounded-[14px] border-2 border-dashed border-blue-200 bg-white p-6 text-center transition-colors hover:border-blue-400 hover:bg-blue-50",
        over && "!border-blue-500 bg-blue-50",
      )}
      disabled={busy}
    >
      {busy ? <LoaderCircle className="size-6 animate-spin text-navy-700" /> : <UploadCloud className="size-6 text-navy-700" />}
      <span className="font-medium">{label}</span>
      <span className="text-[12px] text-muted-foreground">Seret file ke sini atau klik · {accept}</span>
      <input
        ref={input}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onFile(f)
          e.target.value = ""
        }}
      />
    </button>
  )
}

export default function KatalogPage() {
  const { data: products, mutate: mutateProducts } = useSWR<{ items: Product[] }>("/api/kb/products", fetcher)
  const { data: docs, mutate: mutateDocs } = useSWR<{ items: Doc[] }>("/api/kb/documents", fetcher)
  const [busy, setBusy] = useState(false)
  const [docUrl, setDocUrl] = useState("")
  const [docTitle, setDocTitle] = useState("")
  const isAdmin = getUser()?.role === "admin"

  async function upload(path: string, form: FormData, okMsg: (r: Record<string, unknown>) => string) {
    setBusy(true)
    try {
      const r = await api<Record<string, unknown>>(path, { method: "POST", body: form })
      toast.success(okMsg(r))
      mutateProducts()
      mutateDocs()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Unggah gagal")
    } finally {
      setBusy(false)
    }
  }

  async function verify(id: number) {
    await api(`/api/kb/claims/${id}/verify`, { method: "POST" })
    mutateProducts()
  }

  const items = products?.items ?? []
  const synthetic = items.some((p) => p.sumber_data === "sintetis")

  return (
    <div>
      <PageHeader
        title="Katalog"
        description="Knowledge Base: katalog produk, dokumen bersumber, klaim yang disetujui, dan tier harga yang menjadi batas wewenang AI."
        actions={synthetic ? <Pill className="bg-review-bg text-review">Data sintetis berlabel — ganti dengan katalog resmi mitra</Pill> : null}
      />
      <Tabs defaultValue="produk">
        <TabsList className="mb-4">
          <TabsTrigger value="produk">Produk ({items.length})</TabsTrigger>
          <TabsTrigger value="dokumen">Dokumen</TabsTrigger>
          <TabsTrigger value="klaim">Klaim disetujui</TabsTrigger>
          <TabsTrigger value="tier">Tier harga</TabsTrigger>
        </TabsList>

        <TabsContent value="produk" className="space-y-4">
          {isAdmin && (
            <Dropzone
              accept=".csv,.xlsx"
              label="Unggah katalog (CSV/XLSX)"
              busy={busy}
              onFile={(f) => {
                const form = new FormData()
                form.append("file", f)
                form.append("judul", "Katalog Produk (data sintetis)")
                upload("/api/kb/products/import", form, (r) => `Katalog v${r.versi}: ${r.produk} produk, ${r.klaim} klaim baru`)
              }}
            />
          )}
          <Surface className="overflow-x-auto">
            {!products ? (
              <SkeletonRows className="p-4" rows={8} />
            ) : (
              <table className="w-full text-[13px]">
                <thead className="bg-soft text-left text-[12px] tracking-[0.02em] text-muted-foreground">
                  <tr>
                    <th className="sticky left-0 bg-soft px-3 py-2.5 font-medium">SKU</th>
                    <th className="px-3 py-2.5 font-medium">Produk</th>
                    <th className="px-3 py-2.5 font-medium">Izin edar</th>
                    <th className="px-3 py-2.5 font-medium">Kemasan</th>
                    <th className="px-3 py-2.5 text-right font-medium">Harga/karton</th>
                    <th className="px-3 py-2.5 text-right font-medium">MOQ</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((p, i) => (
                    <tr key={p.id} className={cn("border-t border-line", i % 2 ? "bg-canvas" : "bg-white")}>
                      <td className={cn("sticky left-0 px-3 py-2.5 font-mono text-[12px]", i % 2 ? "bg-canvas" : "bg-white")}>{p.sku}</td>
                      <td className="px-3 py-2.5">
                        <div className="font-medium">{p.nama}</div>
                        <div className="line-clamp-1 text-[12px] text-muted-foreground">{p.komposisi}</div>
                      </td>
                      <td className="px-3 py-2.5 font-mono text-[12px] whitespace-nowrap">{p.no_izin_edar}</td>
                      <td className="px-3 py-2.5 text-muted-foreground">{p.kemasan}</td>
                      <td className="tabular px-3 py-2.5 text-right whitespace-nowrap">{formatRp(p.harga_dasar)}</td>
                      <td className="tabular px-3 py-2.5 text-right">{p.moq}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Surface>
        </TabsContent>

        <TabsContent value="dokumen" className="space-y-4">
          {isAdmin && (
            <div className="grid gap-4 lg:grid-cols-2">
              <Dropzone
                accept=".pdf,.docx,.txt,.md"
                label="Unggah dokumen (PDF/DOCX/TXT)"
                busy={busy}
                onFile={(f) => {
                  const form = new FormData()
                  form.append("file", f)
                  form.append("judul", f.name.replace(/\.[^.]+$/, ""))
                  upload("/api/kb/documents", form, (r) => `${r.judul} v${r.versi} di-ingest`)
                }}
              />
              <Panel className="flex flex-col justify-center gap-3 p-5">
                <div className="flex items-center gap-2 font-medium">
                  <Link2 className="size-4 text-navy-700" /> Ingest dari URL
                </div>
                <input value={docTitle} onChange={(e) => setDocTitle(e.target.value)} placeholder="Judul dokumen" className="h-10 rounded-md border border-line bg-white px-3 outline-none focus:border-blue-500" />
                <input value={docUrl} onChange={(e) => setDocUrl(e.target.value)} placeholder="https://…" className="h-10 rounded-md border border-line bg-white px-3 outline-none focus:border-blue-500" />
                <AButton
                  className="self-start"
                  disabled={busy || !docUrl || !docTitle}
                  onClick={() => {
                    const form = new FormData()
                    form.append("judul", docTitle)
                    form.append("url", docUrl)
                    upload("/api/kb/documents", form, (r) => `${r.judul} v${r.versi} di-ingest`)
                  }}
                >
                  <FileUp className="size-4" /> Ingest
                </AButton>
              </Panel>
            </div>
          )}
          <Surface className="divide-y divide-line">
            {docs?.items.map((d) => (
              <div key={d.id} className="flex flex-wrap items-center gap-3 p-4">
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{d.judul}</div>
                  <div className="text-[12px] text-muted-foreground">
                    {d.tipe} · {d.potongan} potongan · diunggah {formatDateTime(d.diunggah_pada)}
                  </div>
                </div>
                <Pill>versi {d.versi}</Pill>
                {d.aktif ? <Pill className="bg-ok-bg text-ok">aktif</Pill> : <Pill>arsip (jejak dipertahankan)</Pill>}
              </div>
            ))}
          </Surface>
        </TabsContent>

        <TabsContent value="klaim">
          <Surface className="divide-y divide-line">
            {items.map((p) => (
              <div key={p.id} className="p-4">
                <div className="mb-2 font-medium">{p.nama}</div>
                <ul className="space-y-2">
                  {p.klaim.map((c) => (
                    <li key={c.id} className="flex flex-wrap items-center gap-2 text-[13px]">
                      <ShieldCheck className="size-4 text-ok" />
                      <span className="min-w-0 flex-1">{c.teks}</span>
                      <span className="text-[12px] text-subtle-foreground">{c.sumber}</span>
                      {c.diverifikasi_oleh ? (
                        <Pill className="bg-ok-bg text-ok">
                          <BadgeCheck className="size-3.5" /> {c.diverifikasi_oleh}
                        </Pill>
                      ) : (
                        <AButton size="sm" variant="outline" onClick={() => verify(c.id)}>
                          Verifikasi
                        </AButton>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </Surface>
        </TabsContent>

        <TabsContent value="tier">
          <Surface className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="bg-soft text-left text-[12px] tracking-[0.02em] text-muted-foreground">
                <tr>
                  <th className="px-3 py-2.5 font-medium">Produk</th>
                  <th className="px-3 py-2.5 font-medium">Tier diskon maksimal yang boleh ditawarkan AI</th>
                </tr>
              </thead>
              <tbody>
                {items.map((p, i) => (
                  <tr key={p.id} className={cn("border-t border-line", i % 2 ? "bg-canvas" : "bg-white")}>
                    <td className="px-3 py-2.5 font-medium">{p.nama}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1.5">
                        {p.tier.map((t) => (
                          <Pill key={t.min_qty}>
                            ≥{t.min_qty} karton: {t.diskon_maks_persen.toLocaleString("id-ID")}%
                          </Pill>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Surface>
          <p className="mt-3 text-[12px] text-muted-foreground">Permintaan diskon di atas tier otomatis dieskalasi ke staf.</p>
        </TabsContent>
      </Tabs>
    </div>
  )
}
