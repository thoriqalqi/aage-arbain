"use client"

import { FileText, Package, ReceiptText, ScrollText, Tag } from "lucide-react"
import { useState } from "react"
import useSWR from "swr"

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { fetcher } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import type { Source } from "@/lib/types"
import { cn } from "@/lib/utils"

type Chunk = {
  id: number
  teks: string
  versi: number
  aktif: boolean
  halaman: number | null
  dokumen: { id: number; judul: string; versi: number; tipe: string; url: string | null; diunggah_pada: string }
}

export function sourceLabel(s: Source): string {
  if (s.chunk_id) {
    const judul = (s.judul || "Dokumen").replace(/\s*\(data sintetis\)/i, "")
    return `${judul} v${s.versi ?? 1}${s.halaman ? ` · bagian ${s.halaman}` : ""}`
  }
  if (s.jenis === "pricing_rules") return s.judul || "Tier harga"
  if (s.jenis === "order_draft") return s.judul || "Pesanan terakhir"
  if (s.jenis === "approval") return `Approval #${s.approval_id}`
  return s.judul || "Template disetujui"
}

function iconFor(s: Source) {
  if (s.chunk_id) return FileText
  if (s.jenis === "pricing_rules") return Tag
  if (s.jenis === "order_draft") return ReceiptText
  if (s.jenis === "produk") return Package
  return ScrollText
}

/** Chip sumber "📄 Katalog v3 · bagian 2" — klik membuka potongan sumber di Sheet (design.md §7.2). */
export function SourceChip({ source, className }: { source: Source; className?: string }) {
  const [open, setOpen] = useState(false)
  const Icon = iconFor(source)
  const clickable = Boolean(source.chunk_id)
  const { data } = useSWR<Chunk>(open && source.chunk_id ? `/api/kb/chunks/${source.chunk_id}` : null, fetcher)
  return (
    <>
      <button
        type="button"
        disabled={!clickable}
        onClick={() => setOpen(true)}
        className={cn(
          "inline-flex h-6 max-w-full items-center gap-1 rounded-full border border-line bg-white/70 px-2 text-[11.5px] text-muted-foreground transition-colors",
          clickable ? "cursor-pointer hover:border-blue-500/40 hover:text-navy-900" : "cursor-default",
          className,
        )}
        title={sourceLabel(source)}
      >
        <Icon className="size-3.5 shrink-0" strokeWidth={1.75} aria-hidden />
        <span className="truncate">{sourceLabel(source)}</span>
      </button>
      {clickable && (
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetContent side="right" className="w-full bg-card sm:max-w-md">
            <SheetHeader>
              <SheetTitle>{data?.dokumen.judul ?? sourceLabel(source)}</SheetTitle>
              <SheetDescription>
                {data
                  ? `Versi ${data.versi} · diunggah ${formatDateTime(data.dokumen.diunggah_pada)}${data.aktif ? "" : " · versi lama (tidak aktif)"}`
                  : "Memuat sumber…"}
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-3 px-4 pb-6">
              <div className="font-mono text-[12px] text-subtle-foreground">chunk #{source.chunk_id}</div>
              <p className="rounded-lg bg-soft p-4 leading-6 whitespace-pre-wrap">{data?.teks ?? source.kutipan}</p>
              {source.skor != null && (
                <p className="text-[12px] text-muted-foreground">Skor relevansi retrieval: {source.skor.toFixed(2)}</p>
              )}
            </div>
          </SheetContent>
        </Sheet>
      )}
    </>
  )
}
