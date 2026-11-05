"use client"

import { CopyCheck, LoaderCircle, ScanSearch } from "lucide-react"
import Link from "next/link"
import { useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { EmptyState, SkeletonRows } from "@/components/aage/empty-state"
import { GalatMuat, LeadsNav } from "@/components/aage/leads-nav"
import { PageHeader, Panel, Surface } from "@/components/aage/panel"
import { Pill } from "@/components/aage/status"
import { ApiError, api, fetcher } from "@/lib/api"
import type { DuplikatTinjauan, LeadRingkas, TinjauanLead } from "@/lib/types"
import { cn } from "@/lib/utils"

function KartuLead({ l, judul }: { l: LeadRingkas; judul: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-white p-3 text-[12.5px]">
      <p className="text-[11.5px] text-subtle-foreground">{judul}</p>
      <Link href={`/leads?prospek=${l.id}`} className="font-medium hover:underline">
        {l.nama}
      </Link>
      <dl className="mt-1 space-y-0.5 text-muted-foreground">
        <div>{l.tipe} · {l.wilayah}</div>
        <div className="line-clamp-2">{l.alamat || "Alamat kosong"}</div>
        <div>Telepon: {l.telepon ?? "kosong"}</div>
        {l.website && <div className="truncate">{l.website}</div>}
        <div>Skor {l.skor} · {l.status} · {l.sumber}</div>
      </dl>
    </div>
  )
}

function KartuDuplikat({ d, onSelesai }: { d: DuplikatTinjauan; onSelesai: () => void }) {
  const [utama, setUtama] = useState<LeadRingkas | null>(null)
  const [busy, setBusy] = useState(false)
  const lain = utama && (utama.id === d.lead.id ? d.cocok : d.lead)

  async function putuskan(keputusan: "digabung" | "bukan_duplikat") {
    setBusy(true)
    try {
      await api(`/api/prospects/duplikat/${d.id}/putuskan`, { method: "POST", json: { keputusan, utama_id: utama?.id ?? null } })
      toast.success(keputusan === "digabung" ? `${lain?.nama} digabung ke ${utama?.nama}` : "Ditandai bukan duplikat")
      onSelesai()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Keputusan gagal disimpan")
      setBusy(false)
    }
  }

  return (
    <Panel className="space-y-3 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Pill className={cn(d.tingkat === "pasti" ? "bg-blocked-bg text-blocked" : "bg-review-bg text-review")}>{d.tingkat === "pasti" ? "Hampir pasti sama" : "Mungkin sama"}</Pill>
        <span className="text-[12.5px] text-muted-foreground">{d.alasan.map((a) => a.keterangan).join("; ")}</span>
      </div>
      <div className="grid gap-2 md:grid-cols-2">
        <KartuLead l={d.lead} judul={`Lead ${d.lead.id}`} />
        <KartuLead l={d.cocok} judul={`Lead ${d.cocok.id}`} />
      </div>
      {utama ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md bg-soft px-3 py-2 text-[12.5px]">
          <span className="min-w-0 flex-1">
            Gabungkan <strong>{lain?.nama}</strong> (lead {lain?.id}) ke <strong>{utama.nama}</strong> (lead {utama.id})? Data kosong diisi, asal data dipindah, dan opt-out ikut. Baris lama tetap tersimpan.
          </span>
          <AButton size="sm" variant="outline" disabled={busy} onClick={() => setUtama(null)}>
            Batal
          </AButton>
          <AButton size="sm" disabled={busy} onClick={() => putuskan("digabung")}>
            {busy && <LoaderCircle className="size-3.5 animate-spin" />} Ya, gabungkan
          </AButton>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <AButton size="sm" variant="outline" disabled={busy} onClick={() => setUtama(d.lead)}>
            Pertahankan lead {d.lead.id}
          </AButton>
          <AButton size="sm" variant="outline" disabled={busy} onClick={() => setUtama(d.cocok)}>
            Pertahankan lead {d.cocok.id}
          </AButton>
          <AButton size="sm" variant="ghost" disabled={busy} onClick={() => putuskan("bukan_duplikat")}>
            Bukan duplikat
          </AButton>
        </div>
      )}
    </Panel>
  )
}

export default function TinjauanPage() {
  const { data, error, isLoading, mutate } = useSWR<TinjauanLead>("/api/prospects/tinjauan", fetcher)
  const [memindai, setMemindai] = useState(false)

  async function pindai() {
    setMemindai(true)
    try {
      const r = await api<{ jumlah: number; calon_baru: number }>("/api/prospects/dedupe/pindai", { method: "POST" })
      toast.success(`${r.jumlah} lead diperiksa, ${r.calon_baru} calon duplikat baru`)
      await mutate()
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Pemeriksaan gagal")
    } finally {
      setMemindai(false)
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader title="Antrean tinjauan" description="Calon duplikat menunggu keputusan staf, tidak pernah digabung otomatis. Lead dengan data kurang tetap bisa dipakai setelah dilengkapi." />
      <LeadsNav />
      {error && !data ? (
        <GalatMuat error={error} onUlang={() => mutate()} />
      ) : isLoading || !data ? (
        <SkeletonRows rows={6} />
      ) : (
        <>
          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-[15px] font-semibold">Calon duplikat ({data.jumlah_duplikat})</h2>
              <AButton size="sm" variant="outline" disabled={memindai} onClick={pindai}>
                {memindai ? <LoaderCircle className="size-3.5 animate-spin" /> : <ScanSearch className="size-3.5" />} Periksa semua lead
              </AButton>
            </div>
            {data.duplikat.length === 0 ? (
              <Surface>
                <EmptyState icon={<CopyCheck />} title="Tidak ada calon duplikat" description="Pasangan yang pernah diputus tidak diangkat lagi." />
              </Surface>
            ) : (
              data.duplikat.map((d) => <KartuDuplikat key={d.id} d={d} onSelesai={() => mutate()} />)
            )}
          </section>
          <section className="space-y-3">
            <h2 className="text-[15px] font-semibold">Perlu dilengkapi atau diverifikasi ({data.jumlah_perlu_tinjauan})</h2>
            <Surface className="overflow-x-auto">
              {data.perlu_tinjauan.length === 0 ? (
                <EmptyState icon={<CopyCheck />} title="Semua lead sudah tertangani" />
              ) : (
                <table className="w-full text-[13px]">
                  <thead className="bg-soft text-left text-[11.5px] tracking-[0.04em] text-muted-foreground uppercase">
                    <tr>
                      <th className="px-4 py-2.5 font-medium">Lead</th>
                      <th className="px-3 py-2.5 font-medium">Alasan</th>
                      <th className="px-3 py-2.5 font-medium">Confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.perlu_tinjauan.map((l) => (
                      <tr key={l.id} className="border-t border-line bg-white align-top">
                        <td className="px-4 py-2.5">
                          <Link href={`/leads?prospek=${l.id}`} className="font-medium hover:underline">
                            {l.nama}
                          </Link>
                          <div className="text-[12px] text-muted-foreground">{l.tipe} · {l.wilayah}</div>
                        </td>
                        <td className="px-3 py-2.5">
                          <ul className="flex flex-wrap gap-1">
                            {l.alasan.map((a) => (
                              <li key={a} className="rounded-full bg-review-bg px-2 py-0.5 text-[12px] whitespace-nowrap text-review">
                                {a}
                              </li>
                            ))}
                          </ul>
                        </td>
                        <td className="tabular px-3 py-2.5">{l.confidence != null ? l.confidence.toLocaleString("id-ID") : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {data.jumlah_perlu_tinjauan > data.perlu_tinjauan.length && (
                <p className="border-t border-line px-4 py-2 text-[12px] text-muted-foreground">Menampilkan {data.perlu_tinjauan.length} dari {data.jumlah_perlu_tinjauan} lead.</p>
              )}
            </Surface>
          </section>
        </>
      )}
    </div>
  )
}
