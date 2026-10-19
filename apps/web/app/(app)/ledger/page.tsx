"use client"

import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table"
import { ArrowUpDown, FileText, Lock } from "lucide-react"
import { useSearchParams } from "next/navigation"
import { Suspense, useMemo, useState } from "react"
import useSWR from "swr"

import { EmptyState, SkeletonRows } from "@/components/aage/empty-state"
import { Panel, PageHeader, Surface } from "@/components/aage/panel"
import { EVENT_META, LedgerTimeline, actorLabel } from "@/components/aage/ledger-timeline"
import { CostChip, Pill, VerdictBadge } from "@/components/aage/status"
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { fetcher } from "@/lib/api"
import { formatDateTime, formatRp } from "@/lib/format"
import type { LedgerEvent } from "@/lib/types"

type Trace = {
  event: LedgerEvent
  rantai: LedgerEvent[]
  sumber: {
    chunk_id: number
    teks: string
    versi: number
    aktif: boolean
    dokumen: { id: number; judul: string; versi: number; tipe: string; diunggah_pada: string; aktif: boolean }
  }[]
  biaya_total_rp: number
  model: string[]
  disetujui_oleh: string | null
}

const selectCls = "h-9 rounded-md border border-line bg-white px-2.5 text-[13px] outline-none focus:border-blue-500"

function TraceSheet({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data } = useSWR<Trace>(id ? `/api/ledger/${id}/trace` : null, fetcher)
  return (
    <Sheet open={id != null} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="w-full overflow-y-auto bg-card sm:max-w-xl">
        <SheetHeader>
          <SheetTitle>Rantai bukti</SheetTitle>
          <SheetDescription>
            {data ? (
              <span className="font-mono text-[12px]">trace {data.event.trace_id ?? "—"} · event #{data.event.id}</span>
            ) : (
              "Memuat…"
            )}
          </SheetDescription>
        </SheetHeader>
        {data && (
          <div className="space-y-6 px-4 pb-8">
            <div className="grid grid-cols-2 gap-3 text-[13px]">
              <div className="rounded-lg bg-soft p-3">
                <div className="text-[12px] text-muted-foreground">Total biaya rantai</div>
                <div className="tabular text-lg font-semibold">{formatRp(data.biaya_total_rp, { decimals: true })}</div>
              </div>
              <div className="rounded-lg bg-soft p-3">
                <div className="text-[12px] text-muted-foreground">Disetujui oleh</div>
                <div className="font-semibold">{data.disetujui_oleh ? actorLabel(data.disetujui_oleh) : "Otomatis (AI)"}</div>
              </div>
              <div className="col-span-2 rounded-lg bg-soft p-3">
                <div className="text-[12px] text-muted-foreground">Model</div>
                <div className="font-mono text-[12px]">{data.model.join(", ") || "—"}</div>
              </div>
            </div>
            <section>
              <h3 className="mb-3 text-[13px] font-semibold">Event ({data.rantai.length})</h3>
              <LedgerTimeline events={data.rantai} highlightId={data.event.id} />
            </section>
            <section>
              <h3 className="mb-3 text-[13px] font-semibold">Dokumen sumber</h3>
              {data.sumber.length === 0 ? (
                <p className="text-[13px] text-muted-foreground">Rantai ini memakai template/tabel harga yang disetujui, tanpa potongan dokumen.</p>
              ) : (
                <ul className="space-y-3">
                  {data.sumber.map((s) => (
                    <li key={s.chunk_id} className="rounded-lg border border-line p-3">
                      <div className="flex flex-wrap items-center gap-2 text-[13px]">
                        <FileText className="size-4 text-navy-700" />
                        <span className="font-semibold">{s.dokumen.judul}</span>
                        <Pill>versi {s.versi}</Pill>
                        {!s.aktif && <Pill className="bg-review-bg text-review">versi lama</Pill>}
                      </div>
                      <div className="mt-1 font-mono text-[11px] text-subtle-foreground">
                        chunk #{s.chunk_id} · diunggah {formatDateTime(s.dokumen.diunggah_pada)}
                      </div>
                      <p className="mt-2 line-clamp-6 text-[13px] leading-6 text-muted-foreground">{s.teks}</p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}

function LedgerInner() {
  const params = useSearchParams()
  const [tipe, setTipe] = useState("")
  const [verdict, setVerdict] = useState("")
  const [aktor, setAktor] = useState("")
  const [dari, setDari] = useState("")
  const [limit, setLimit] = useState(100)
  const [sorting, setSorting] = useState<SortingState>([])
  const [open, setOpen] = useState<number | null>(null)
  const convId = params.get("conversation_id")

  const qs = new URLSearchParams()
  if (tipe) qs.set("tipe", tipe)
  if (verdict) qs.set("verdict", verdict)
  if (aktor) qs.set("aktor", aktor)
  if (dari) qs.set("dari", new Date(dari).toISOString())
  if (convId) qs.set("conversation_id", convId)
  qs.set("limit", String(limit))
  const { data } = useSWR<{ total: number; items: LedgerEvent[]; tipe: Record<string, string> }>(`/api/ledger?${qs}`, fetcher, {
    refreshInterval: 10000,
  })

  const columns = useMemo<ColumnDef<LedgerEvent>[]>(
    () => [
      { accessorKey: "id", header: "ID", cell: (c) => <span className="font-mono text-[12px] text-subtle-foreground">#{c.getValue<number>()}</span> },
      { accessorKey: "waktu", header: "Waktu", cell: (c) => <span className="tabular whitespace-nowrap">{formatDateTime(c.getValue<string>())}</span> },
      {
        accessorKey: "tipe_event",
        header: "Event",
        cell: (c) => {
          const m = EVENT_META[c.getValue<string>()]
          const Icon = m?.icon
          return (
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap font-medium">
              {Icon && <Icon className="size-3.5 text-navy-700" />} {m?.label ?? c.getValue<string>()}
            </span>
          )
        },
      },
      { accessorKey: "ringkasan", header: "Ringkasan", enableSorting: false, cell: (c) => <span className="line-clamp-1 max-w-[28rem] text-muted-foreground">{c.getValue<string>()}</span> },
      { accessorKey: "verdict", header: "Verdict", cell: (c) => <VerdictBadge verdict={c.row.original.verdict} rules={c.row.original.aturan_terpicu} /> },
      { accessorKey: "aktor", header: "Aktor", cell: (c) => <span className="whitespace-nowrap">{actorLabel(c.getValue<string>())}</span> },
      { accessorKey: "model", header: "Model", cell: (c) => <span className="font-mono text-[11px] whitespace-nowrap text-subtle-foreground">{c.getValue<string>() ?? "—"}</span> },
      { accessorKey: "biaya_rp", header: "Biaya", cell: (c) => <CostChip value={c.getValue<number>()} /> },
      { accessorKey: "trace_id", header: "Trace", enableSorting: false, cell: (c) => <span className="font-mono text-[11px] text-subtle-foreground">{c.getValue<string>()?.slice(0, 8) ?? "—"}</span> },
    ],
    [],
  )
  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  return (
    <div>
      <PageHeader
        title="Ledger"
        description="Evidence-to-Action Ledger: setiap aksi AI dan staf, append-only. Klik baris untuk menelusuri rantai sampai dokumen sumber."
        actions={
          <span className="inline-flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Lock className="size-3.5" /> append-only · {data?.total ?? "…"} event
          </span>
        }
      />
      <Panel className="mb-4 flex flex-wrap items-end gap-3 p-4">
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Tipe event
          <select value={tipe} onChange={(e) => setTipe(e.target.value)} className={selectCls}>
            <option value="">Semua</option>
            {Object.entries(data?.tipe ?? {}).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Verdict
          <select value={verdict} onChange={(e) => setVerdict(e.target.value)} className={selectCls}>
            <option value="">Semua</option>
            <option value="allowed">Diizinkan</option>
            <option value="review">Perlu review</option>
            <option value="blocked">Diblokir</option>
          </select>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Aktor
          <select value={aktor} onChange={(e) => setAktor(e.target.value)} className={selectCls}>
            <option value="">Semua</option>
            <option value="AI">AI</option>
            <option value="staf">Staf</option>
            <option value="pembeli">Pembeli</option>
          </select>
        </label>
        <label className="grid gap-1 text-[12px] text-muted-foreground">
          Sejak tanggal
          <input type="date" value={dari} onChange={(e) => setDari(e.target.value)} className={selectCls} />
        </label>
        {convId && <Pill className="mb-1.5">Percakapan #{convId}</Pill>}
      </Panel>

      <Surface className="overflow-x-auto">
        {!data ? (
          <SkeletonRows className="p-4" rows={10} />
        ) : data.items.length === 0 ? (
          <EmptyState title="Tidak ada event" description="Ubah filter untuk melihat event lain." />
        ) : (
          <table className="w-full text-[13px]">
            <thead className="sticky top-0 bg-soft text-left text-[12px] tracking-[0.02em] text-muted-foreground">
              {table.getHeaderGroups().map((hg) => (
                <tr key={hg.id}>
                  {hg.headers.map((h) => (
                    <th key={h.id} className="px-3 py-2.5 font-medium first:sticky first:left-0 first:bg-soft">
                      {h.column.getCanSort() ? (
                        <button className="inline-flex items-center gap-1" onClick={h.column.getToggleSortingHandler()}>
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          <ArrowUpDown className="size-3 opacity-50" />
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row, i) => (
                <tr
                  key={row.id}
                  onClick={() => setOpen(row.original.id)}
                  className={`cursor-pointer border-t border-line hover:bg-blue-50 ${i % 2 ? "bg-canvas" : "bg-white"}`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className={`px-3 py-2 align-middle first:sticky first:left-0 ${i % 2 ? "first:bg-canvas" : "first:bg-white"}`}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Surface>
      {data && data.total > data.items.length && (
        <div className="mt-4 flex justify-center">
          <button onClick={() => setLimit((l) => Math.min(500, l + 100))} className="h-9 rounded-md px-4 text-[13px] font-medium text-navy-700 hover:bg-soft">
            Muat lebih banyak ({data.items.length} dari {data.total})
          </button>
        </div>
      )}
      <TraceSheet id={open} onClose={() => setOpen(null)} />
    </div>
  )
}

export default function LedgerPage() {
  return (
    <Suspense fallback={<SkeletonRows rows={10} />}>
      <LedgerInner />
    </Suspense>
  )
}
