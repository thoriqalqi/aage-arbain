"use client"

import { ArrowUpRight, Download } from "lucide-react"
import Link from "next/link"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { FunnelChart, KpiTile, VolumeChart, WeekBars } from "@/components/aage/charts"
import { EmptyState, SkeletonRows } from "@/components/aage/empty-state"
import { CardHeader, PageHeader, Panel } from "@/components/aage/panel"
import { VerdictBadge } from "@/components/aage/status"
import { fetcher } from "@/lib/api"
import { contactName, formatDay, formatDuration, formatNum, formatPct, formatRp, relativeTime } from "@/lib/format"
import { ROLE_LABEL, useRole, type Role } from "@/lib/rbac"
import { INTENT_LABEL, type Approval, type ContentDraft, type Kpi } from "@/lib/types"

const SUBTITLE: Record<Role, string> = {
  admin: "Gambaran penjualan, konten, kepatuhan, dan biaya AI dalam 14 hari terakhir.",
  sales: "Percakapan WhatsApp, eskalasi yang menunggu Anda, dan perkembangan lead.",
  marketing: "Konten yang sedang disiapkan dan hasil pemeriksaan klaim oleh ClaimGuard.",
}

function greeting() {
  const h = new Date().getHours()
  return h < 11 ? "Selamat pagi" : h < 15 ? "Selamat siang" : h < 18 ? "Selamat sore" : "Selamat malam"
}

function TileSkeleton() {
  return (
    <>
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="shimmer h-[124px] rounded-2xl" />
      ))}
    </>
  )
}

function ActionQueue({ items }: { items: Approval[] | undefined }) {
  return (
    <Panel className="overflow-hidden">
      <div className="p-5 pb-4">
        <CardHeader
          title="Butuh tindakan"
          aside={
            <Link href="/approval" className="inline-flex items-center gap-1 text-[13px] font-medium text-brand-600 hover:underline">
              Lihat semua <ArrowUpRight className="size-3.5" />
            </Link>
          }
        />
      </div>
      {!items ? (
        <SkeletonRows rows={4} className="px-5 pb-5" />
      ) : items.length === 0 ? (
        <EmptyState title="Antrean kosong" description="Semua percakapan sudah ditangani agen atau staf." className="py-8" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead className="border-y border-line bg-canvas text-left text-[12px] text-muted-foreground">
              <tr>
                <th className="px-5 py-2.5 font-medium">Pembeli</th>
                <th className="px-3 py-2.5 font-medium">Intent</th>
                <th className="px-3 py-2.5 font-medium">Alasan</th>
                <th className="px-3 py-2.5 font-medium">ClaimGuard</th>
                <th className="px-5 py-2.5 text-right font-medium">Menunggu</th>
              </tr>
            </thead>
            <tbody>
              {items.slice(0, 6).map((a) => (
                <tr key={a.id} className="border-b border-line last:border-0 hover:bg-canvas">
                  <td className="px-5 py-3">
                    <Link href={`/approval?id=${a.id}`} className="font-medium hover:text-brand-600">
                      {contactName(a.contact)}
                    </Link>
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-muted-foreground">{INTENT_LABEL[a.intent ?? ""] ?? a.intent}</td>
                  <td className="max-w-[18rem] px-3 py-3 text-muted-foreground">
                    <span className="line-clamp-1">{a.alasan}</span>
                  </td>
                  <td className="px-3 py-3">{a.verdict ? <VerdictBadge verdict={a.verdict} /> : <span className="text-subtle-foreground">—</span>}</td>
                  <td className="px-5 py-3 text-right whitespace-nowrap text-muted-foreground">{relativeTime(a.dibuat_pada)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

function VolumePanel({ kpi, className }: { kpi: Kpi | undefined; className?: string }) {
  return (
    <Panel className={className ?? "p-5"}>
      <CardHeader title="Volume chat" aside={<span className="text-[12px] text-subtle-foreground">harian</span>} />
      <div className="mt-3 mb-5">
        <span className="tabular text-[28px] leading-9 font-semibold tracking-tight">{formatNum(kpi?.ringkasan.pesan_masuk)}</span>
        <span className="ml-1.5 text-[13px] text-muted-foreground">pesan masuk</span>
      </div>
      {kpi ? <VolumeChart data={kpi.harian} /> : <div className="shimmer h-60 rounded-lg" />}
    </Panel>
  )
}

function FunnelPanel({ kpi }: { kpi: Kpi | undefined }) {
  return (
    <Panel className="p-5">
      <CardHeader title="Funnel lead" aside={<span className="text-[12px] text-subtle-foreground">dari Ledger</span>} />
      <div className="mt-5">{kpi ? <FunnelChart data={kpi.funnel} /> : <SkeletonRows rows={5} />}</div>
    </Panel>
  )
}

function PermintaanPanel({ kpi }: { kpi: Kpi | undefined }) {
  const data = kpi?.permintaan_tak_terpenuhi
  return (
    <Panel className="p-5">
      <CardHeader title="Dicari, belum ada di katalog" aside={<span className="text-[12px] text-subtle-foreground">{formatNum(data?.total)} permintaan</span>} />
      {!data ? (
        <SkeletonRows rows={4} className="mt-4" />
      ) : data.teratas.length === 0 ? (
        <EmptyState title="Belum ada permintaan" description="Barang yang dicari pembeli tetapi tidak ada di katalog akan muncul di sini." className="py-8" />
      ) : (
        <ul className="mt-3 divide-y divide-line text-[13px]">
          {data.teratas.map((p) => (
            <li key={p.istilah} className="flex items-center gap-3 py-2.5">
              <span className="min-w-0 flex-1 truncate font-medium">{p.istilah}</span>
              <span className="whitespace-nowrap text-muted-foreground">{p.terakhir ? relativeTime(p.terakhir) : ""}</span>
              <span className="tabular w-8 text-right font-medium">{formatNum(p.jumlah)}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

function ContentPanel({ items }: { items: ContentDraft[] | undefined }) {
  return (
    <Panel className="overflow-hidden">
      <div className="p-5 pb-4">
        <CardHeader
          title="Konten terbaru"
          aside={
            <Link href="/konten" className="inline-flex items-center gap-1 text-[13px] font-medium text-brand-600 hover:underline">
              Studio Konten <ArrowUpRight className="size-3.5" />
            </Link>
          }
        />
      </div>
      {!items ? (
        <SkeletonRows rows={4} className="px-5 pb-5" />
      ) : items.length === 0 ? (
        <EmptyState title="Belum ada konten" description="Buat draf pertama di Studio Konten." className="py-8" />
      ) : (
        <ul className="divide-y divide-line border-t border-line">
          {items.slice(0, 6).map((c) => (
            <li key={c.id} className="flex items-center gap-3 px-5 py-3 text-[13px]">
              <div className="min-w-0 flex-1">
                <Link href={`/konten?id=${c.id}`} className="line-clamp-1 font-medium hover:text-brand-600">
                  {c.judul}
                </Link>
                <div className="text-[12px] text-muted-foreground">
                  {c.tipe === "artikel" ? "Artikel" : "Deskripsi"} · {c.status} · {relativeTime(c.dibuat_pada)}
                </div>
              </div>
              <VerdictBadge verdict={c.claim_verdict} />
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

export default function RingkasanPage() {
  const { user, role } = useRole()
  const { data: kpi } = useSWR<Kpi>("/api/kpi", fetcher, { refreshInterval: 15000 })
  const { data: ap } = useSWR<{ items: Approval[] }>("/api/approvals?status=menunggu", fetcher, { refreshInterval: 8000 })
  const { data: content } = useSWR<{ items: ContentDraft[] }>(role !== "sales" ? "/api/content" : null, fetcher)
  const r = kpi?.ringkasan
  const days = kpi?.harian ?? []
  const range = days.length ? `${formatDay(days[0].tanggal)} – ${formatDay(days[days.length - 1].tanggal)}` : "14 hari"

  function exportCsv() {
    if (!kpi) return
    const rows = [["tanggal", "chat", "pesan", "otomatis", "eskalasi", "diblokir"], ...kpi.harian.map((d) => [d.tanggal, d.chat, d.pesan, d.otomatis, d.eskalasi, d.diblokir])]
    const a = document.createElement("a")
    a.href = URL.createObjectURL(new Blob([rows.map((x) => x.join(",")).join("\n")], { type: "text/csv" }))
    a.download = "kpi-aage.csv"
    a.click()
  }

  const drafts = content?.items.filter((c) => c.status === "draf").length ?? 0

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow={`Ringkasan · ${ROLE_LABEL[role]}`}
        title={`${greeting()}, ${user?.nama?.split(" ")[0] ?? ""}`}
        description={SUBTITLE[role]}
        actions={
          <>
            <span className="tabular text-[12.5px] text-muted-foreground">{range}</span>
            {role === "admin" && (
              <AButton size="sm" variant="glass" onClick={exportCsv} disabled={!kpi}>
                <Download className="size-4" /> Ekspor CSV
              </AButton>
            )}
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {!r ? (
          <TileSkeleton />
        ) : role === "sales" ? (
          <>
            <KpiTile label="Chat 14 hari" value={r.chat} delta={kpi?.delta.chat} hint={`${formatNum(r.pesan_masuk)} pesan masuk`} />
            <KpiTile label="Dijawab otomatis" value={r.otomatis_persen} format={formatPct} delta={kpi?.delta.otomatis_persen} deltaFormat={formatPct} hint="bersumber dari Knowledge Base" />
            <KpiTile label="Menunggu Anda" value={ap?.items.length ?? 0} hint="harga, MOQ, negosiasi, klaim" />
            <KpiTile label="Respons staf rata-rata" value={r.respons_staf_rata_menit ?? 0} format={(v) => (r.respons_staf_rata_menit == null ? "—" : `${formatNum(v)} mnt`)} hint="sejak eskalasi masuk" />
          </>
        ) : role === "marketing" ? (
          <>
            <KpiTile label="Draf konten" value={drafts} hint={`${content?.items.length ?? 0} konten total`} />
            <KpiTile label="Klaim diblokir" value={r.klaim_diblokir} delta={kpi?.delta.klaim_diblokir} deltaGoodWhenUp={false} hint="tidak pernah terbit" />
            <KpiTile label="Perlu review" value={r.klaim_ditahan} hint="masuk antrean approval" />
            <KpiTile label="Biaya AI / percakapan" value={r.biaya_per_percakapan_rp} format={(v) => formatRp(v, { decimals: true })} hint={`total ${formatRp(r.biaya_total_rp, { decimals: true })}`} />
          </>
        ) : (
          <>
            <KpiTile label="Chat 14 hari" value={r.chat} delta={kpi?.delta.chat} hint={`${formatNum(r.pesan_masuk)} pesan masuk`} info="Jumlah percakapan unik dengan pesan masuk dalam periode." />
            <KpiTile label="Dijawab otomatis" value={r.otomatis_persen} format={formatPct} delta={kpi?.delta.otomatis_persen} deltaFormat={formatPct} hint={`Respons AI p95 ${formatDuration(r.respons_ai_p95_ms)}`} info="Persentase keputusan kebijakan 'kirim' tanpa staf." />
            <KpiTile label="Klaim diblokir" value={r.klaim_diblokir} delta={kpi?.delta.klaim_diblokir} deltaGoodWhenUp={false} hint={`${r.klaim_ditahan} draf ditahan untuk review`} info="Klaim terapi yang dihentikan ClaimGuard (masuk & keluar)." />
            <KpiTile label="Biaya AI / percakapan" value={r.biaya_per_percakapan_rp} format={(v) => formatRp(v, { decimals: true })} delta={kpi?.delta.biaya_per_percakapan_rp} deltaGoodWhenUp={false} deltaFormat={(v) => formatRp(v, { decimals: true })} hint={`Total ${formatRp(r.biaya_total_rp, { decimals: true })}`} info="Total biaya LLM dibagi jumlah percakapan." />
          </>
        )}
      </div>

      {role === "marketing" ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <ContentPanel items={content?.items} />
          <ActionQueue items={ap?.items} />
        </div>
      ) : (
        <>
          <div className="grid gap-5 lg:grid-cols-3">
            <VolumePanel kpi={kpi} className="p-5 lg:col-span-2" />
            {role === "sales" ? (
              <FunnelPanel kpi={kpi} />
            ) : (
              <Panel className="flex flex-col p-5">
                <CardHeader title="Pesan 7 hari" aside={<span className="text-[12px] text-subtle-foreground">harian</span>} />
                <div className="mt-auto pt-4">
                  {kpi ? <WeekBars data={days.slice(-7).map((d) => ({ tanggal: d.tanggal, value: d.pesan }))} /> : <div className="shimmer h-56 rounded-lg" />}
                </div>
              </Panel>
            )}
          </div>
          <div className="grid gap-5 lg:grid-cols-3">
            {role === "admin" ? <FunnelPanel kpi={kpi} /> : <ContentPanelPlaceholder />}
            <div className="lg:col-span-2">
              <ActionQueue items={ap?.items} />
            </div>
          </div>
          <PermintaanPanel kpi={kpi} />
        </>
      )}
    </div>
  )
}

/** Sales: pintasan ke Leads sebagai pengganti panel konten. */
function ContentPanelPlaceholder() {
  return (
    <Panel className="flex flex-col justify-between gap-6 p-5">
      <div>
        <CardHeader title="Prospek baru" />
        <p className="mt-2 text-[13px] text-muted-foreground">Petakan apotek dan toko obat di wilayah Anda, lalu lihat skor peluang dan langkah berikutnya.</p>
      </div>
      <Link href="/leads" className="btn-liquid inline-flex h-9 items-center justify-center gap-1.5 self-start rounded-[10px] px-4 text-[13px] font-medium">
        Buka Leads <ArrowUpRight className="size-4" />
      </Link>
    </Panel>
  )
}
