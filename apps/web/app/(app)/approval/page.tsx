"use client"

import { ArrowDownUp, Bot, Check, Keyboard, Megaphone, MessageSquareText, Pencil, ReceiptText, Search, X } from "lucide-react"
import Link from "next/link"
import { motion } from "motion/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { WaText } from "@/components/aage/chat-bubble"
import { EmptyState, SkeletonRows } from "@/components/aage/empty-state"
import { WaitBadge } from "@/components/aage/inbox-panels"
import { PageHeader } from "@/components/aage/panel"
import { Pill, VerdictBadge } from "@/components/aage/status"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { ApiError, api, fetcher } from "@/lib/api"
import { contactName, relativeTime } from "@/lib/format"
import { INTENT_LABEL, type Approval, type CheckResult } from "@/lib/types"
import { cn } from "@/lib/utils"

const AGENT_LABEL: Record<string, string> = {
  agen_negosiasi: "Eskalasi negosiasi · Sales Agent",
  agen_deal_final: "Deal final · Sales Agent",
  agen_konten: "Konten GEO · GEO Agent",
}

type Jenis = "balasan" | "order_draft" | "agen" | "konten"

const FILTER: { key: Jenis | ""; label: string }[] = [
  { key: "", label: "Semua" },
  { key: "balasan", label: "Balasan chat" },
  { key: "order_draft", label: "Pesanan" },
  { key: "agen", label: "Agen" },
  { key: "konten", label: "Konten" },
]

function jenisOf(a: Approval): Jenis {
  if (a.objek_tipe === "order_draft" || a.objek_tipe === "konten") return a.objek_tipe
  return a.objek_tipe.startsWith("agen_") ? "agen" : "balasan"
}

const NAMA_AGEN: Record<string, string> = { agen_konten: "GEO Agent" }

function namaOf(a: Approval) {
  const jenis = jenisOf(a)
  if (jenis === "konten") return "Studio Konten"
  if (jenis === "agen") return NAMA_AGEN[a.objek_tipe] ?? "Sales Agent" // approval agen tidak terhubung ke pelanggan
  return contactName(a.contact)
}

const dariPelanggan = (a: Approval) => ["balasan", "order_draft"].includes(jenisOf(a))

function labelOf(a: Approval) {
  const jenis = jenisOf(a)
  return AGENT_LABEL[a.objek_tipe] ?? (jenis === "order_draft" ? `Draf pesanan #${a.objek_id}` : jenis === "konten" ? "Konten pemasaran" : "Balasan chat")
}

function IkonJenis({ a, className }: { a: Approval; className?: string }) {
  const jenis = jenisOf(a)
  if (jenis === "order_draft") return <ReceiptText className={className} aria-hidden />
  if (jenis === "konten") return <Megaphone className={className} aria-hidden />
  if (jenis === "agen") return <Bot className={className} aria-hidden />
  return <MessageSquareText className={className} aria-hidden />
}

function BarisAntrean({ a, dipilih, onPilih }: { a: Approval; dipilih: boolean; onPilih: () => void }) {
  const ref = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (dipilih) ref.current?.scrollIntoView({ block: "nearest" })
  }, [dipilih])
  return (
    <button
      ref={ref}
      type="button"
      onClick={onPilih}
      aria-current={dipilih ? "true" : undefined}
      className={cn("flex w-full gap-3 border-b border-line/70 px-3 py-3 text-left transition-colors hover:bg-soft/70", dipilih && "bg-brand-50")}
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-line text-forest-900">
        <IkonJenis a={a} className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="truncate font-medium">{namaOf(a)}</span>
          <WaitBadge since={a.dibuat_pada} className="ml-auto shrink-0" />
        </span>
        <span className="line-clamp-2 text-[12.5px] text-muted-foreground">{a.alasan}</span>
      </span>
    </button>
  )
}

function DetailApproval({
  a,
  editing,
  onEdit,
  onDecide,
  onKembali,
  busy,
  error,
}: {
  a: Approval
  editing: boolean
  onEdit: (v: boolean) => void
  onDecide: (aksi: "setujui" | "edit" | "tolak", teks?: string) => void
  onKembali: () => void
  busy: boolean
  error: CheckResult | null
}) {
  const [draft, setDraft] = useState(a.draf)
  const area = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    if (editing) area.current?.focus()
  }, [editing])
  const [head, ...lines] = a.ringkasan.split("\n")
  const isContent = a.objek_tipe === "konten"
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.16 }} className="flex h-full min-h-0 flex-col">
      <button type="button" onClick={onKembali} className="border-b px-4 py-2 text-left text-[13px] text-forest-700 md:hidden">
        ← Semua approval
      </button>
      <div className="flex flex-wrap items-start gap-x-3 gap-y-1 border-b px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold">{namaOf(a)}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Pill>
              <IkonJenis a={a} className="size-3.5" />
              {labelOf(a)}
            </Pill>
            {a.intent && !isContent && <Pill>{INTENT_LABEL[a.intent] ?? a.intent}</Pill>}
            <span className="text-[12px] text-subtle-foreground">menunggu {relativeTime(a.dibuat_pada).replace(" lalu", "")}</span>
          </div>
        </div>
        {a.conversation_id && (
          <Link href={`/inbox?id=${a.conversation_id}`} className="text-[13px] font-medium text-forest-700 hover:underline">
            Buka chat
          </Link>
        )}
        {isContent && a.objek_id && (
          <Link href={`/konten?id=${a.objek_id}`} className="text-[13px] font-medium text-forest-700 hover:underline">
            Buka di Studio
          </Link>
        )}
      </div>

      <div className="scrollbar-thin min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <p className="text-[13px] text-escalate">
          <span className="font-semibold">Alasan:</span> {a.alasan}
        </p>
        <div className="rounded-lg bg-soft/80 p-3 text-[13px]">
          <div className="mb-1.5 text-[12px] font-medium text-muted-foreground">{head}</div>
          <div className="space-y-1">
            {lines.map((l, i) => (
              <p key={i} className="line-clamp-3 text-muted-foreground">
                <span className="font-medium text-foreground">{l.split(":")[0]}:</span>
                {l.slice(l.indexOf(":") + 1)}
              </p>
            ))}
          </div>
        </div>
        <div>
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="text-[12px] font-medium text-muted-foreground">{isContent ? "Isi konten" : "Draf balasan untuk pembeli"}</span>
            <VerdictBadge verdict={a.verdict} />
          </div>
          {editing ? (
            <textarea
              ref={area}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={6}
              className="w-full rounded-lg border border-line bg-white p-3 text-[14px] leading-6 outline-none focus:border-brand-500"
              aria-label="Edit draf balasan"
              onKeyDown={(e) => {
                if (e.key === "Escape") onEdit(false)
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) onDecide("edit", draft)
              }}
            />
          ) : (
            <div className="rounded-lg border border-line bg-white p-3 leading-6 break-words whitespace-pre-wrap">
              {a.draf ? <WaText text={a.draf} /> : <span className="text-subtle-foreground">Belum ada draf — tulis balasan lewat Edit.</span>}
            </div>
          )}
          {error && (
            <div className="mt-2 rounded-md bg-blocked-bg p-2.5 text-[13px] text-blocked">
              <div className="flex items-center gap-2 font-semibold">
                <VerdictBadge verdict={error.verdict} rules={error.rules_triggered} animate /> ClaimGuard menahan teks ini
              </div>
              <button className="mt-1 text-left underline" onClick={() => setDraft(error.safe_text)}>
                Ganti dengan versi aman
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-t border-line p-3">
        {editing ? (
          <>
            <AButton className="flex-1 sm:flex-none" onClick={() => onDecide("edit", draft)} disabled={busy || !draft.trim()}>
              <Check className="size-4" /> Simpan & kirim
            </AButton>
            <AButton variant="ghost" onClick={() => onEdit(false)}>
              Batal
            </AButton>
          </>
        ) : (
          <>
            <AButton className="flex-1 sm:flex-none" onClick={() => onDecide("setujui")} disabled={busy || !a.draf}>
              <Check className="size-4" /> {isContent ? "Setujui" : "Setujui & kirim"} <kbd className="ml-1 hidden font-mono text-[11px] opacity-60 md:inline">A</kbd>
            </AButton>
            {!isContent && (
              <AButton variant="outline" onClick={() => onEdit(true)} disabled={busy}>
                <Pencil className="size-4" /> Edit <kbd className="ml-1 hidden font-mono text-[11px] opacity-60 md:inline">E</kbd>
              </AButton>
            )}
            <AButton variant="destructive" onClick={() => onDecide("tolak")} disabled={busy}>
              <X className="size-4" /> Tolak <kbd className="ml-1 hidden font-mono text-[11px] opacity-60 md:inline">R</kbd>
            </AButton>
            <span className="ml-auto hidden items-center gap-1.5 text-[12px] text-muted-foreground lg:inline-flex">
              <Keyboard className="size-4" aria-hidden /> J/K pindah
            </span>
          </>
        )}
      </div>
    </motion.div>
  )
}

function dampakKeputusan(a: Approval, aksi: "setujui" | "tolak") {
  if (aksi === "tolak") return "Tidak ada pesan yang terkirim."
  if (a.objek_tipe === "konten") return "Konten ditandai disetujui dan siap diekspor di Studio Konten."
  return a.conversation_id ? "Draf ini langsung terkirim ke pembeli." : "Tidak ada pesan yang terkirim karena approval ini tidak terhubung ke chat."
}

/** Pintas keyboard hanya satu ketukan, jadi keputusannya dikonfirmasi. Fokus awal di Batal supaya ketukan nyasar tidak mengirim apa pun. */
function KonfirmasiPintas({ a, aksi, onBatal, onYakin }: { a: Approval; aksi: "setujui" | "tolak"; onBatal: () => void; onYakin: () => void }) {
  const batal = useRef<HTMLButtonElement>(null)
  const setuju = aksi === "setujui"
  return (
    <Dialog open onOpenChange={(o) => !o && onBatal()}>
      <DialogContent initialFocus={batal}>
        <DialogHeader>
          <DialogTitle>{setuju ? "Setujui approval ini?" : "Tolak approval ini?"}</DialogTitle>
          <DialogDescription>
            {namaOf(a)} · {dampakKeputusan(a, aksi)}
          </DialogDescription>
        </DialogHeader>
        {a.draf && <p className="scrollbar-thin max-h-40 overflow-y-auto rounded-lg border border-line bg-soft p-3 text-[13px] break-words whitespace-pre-wrap">{a.draf}</p>}
        <DialogFooter>
          <AButton ref={batal} variant="outline" onClick={onBatal}>
            Batal
          </AButton>
          <AButton variant={setuju ? "default" : "destructive"} onClick={onYakin}>
            {setuju ? <Check className="size-4" /> : <X className="size-4" />} {setuju ? "Ya, setujui" : "Ya, tolak"}
          </AButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default function ApprovalPage() {
  const { data, mutate } = useSWR<{ items: Approval[] }>("/api/approvals?status=menunggu", fetcher, { refreshInterval: 6000 })
  const items = useMemo(() => data?.items ?? [], [data])
  const [pilihId, setPilihId] = useState<number | null>(null)
  const [posisi, setPosisi] = useState(0)
  const [bukaDetail, setBukaDetail] = useState(false)
  const [tab, setTab] = useState<"antrean" | "riwayat">("antrean")
  const [filter, setFilter] = useState<Jenis | "">("")
  const [q, setQ] = useState("")
  const [terbaru, setTerbaru] = useState(false)
  const [editing, setEditing] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<Record<number, CheckResult>>({})
  const [konfirmasi, setKonfirmasi] = useState<{ a: Approval; aksi: "setujui" | "tolak" } | null>(null)
  const { data: history } = useSWR<{ items: Approval[] }>("/api/approvals?status=semua", fetcher, { refreshInterval: 15000 })

  const jumlah = useMemo(() => {
    const hasil: Partial<Record<Jenis, number>> = {}
    for (const a of items) hasil[jenisOf(a)] = (hasil[jenisOf(a)] ?? 0) + 1
    return hasil
  }, [items])

  const tampil = useMemo(() => {
    const kata = q.trim().toLowerCase()
    const hasil = items.filter((a) => (!filter || jenisOf(a) === filter) && (!kata || `${namaOf(a)} ${a.alasan} ${a.draf ?? ""}`.toLowerCase().includes(kata)))
    const urut = terbaru ? [...hasil].reverse() : hasil
    return [...urut.filter(dariPelanggan), ...urut.filter((a) => !dariPelanggan(a))]
  }, [items, filter, q, terbaru])

  // Pilihan mengikuti id, bukan urutan, supaya data baru tidak menggeser approval yang sedang dibaca staf.
  const idx = tampil.findIndex((a) => a.id === pilihId)
  const aktifIdx = idx >= 0 ? idx : Math.min(posisi, tampil.length - 1)
  const aktif = tampil[aktifIdx]

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id")
    if (id) {
      setPilihId(Number(id))
      setBukaDetail(true)
    }
  }, [])

  useEffect(() => {
    if (aktif && aktif.id !== pilihId) setPilihId(aktif.id)
    if (aktifIdx >= 0 && aktifIdx !== posisi) setPosisi(aktifIdx)
  }, [aktif, aktifIdx, pilihId, posisi])

  const decide = useCallback(
    async (a: Approval, aksi: "setujui" | "edit" | "tolak", teks?: string) => {
      setBusy(true)
      try {
        await api(`/api/approvals/${a.id}/decide`, { method: "POST", json: { aksi, teks } })
        setEditing(null)
        await mutate({ items: items.filter((x) => x.id !== a.id) }, { revalidate: true })
        if (aksi === "tolak") toast("Draf ditolak — tidak ada pesan terkirim.")
        else
          toast.success(
            a.objek_tipe === "order_draft"
              ? "Pesanan dikonfirmasi & terkirim ke WhatsApp"
              : a.objek_tipe === "konten"
                ? "Konten disetujui — siap diekspor di Studio Konten"
                : "Terkirim ke WhatsApp",
          )
      } catch (err) {
        if (err instanceof ApiError && (err.detail as { claimguard?: CheckResult })?.claimguard) {
          setErrors((e) => ({ ...e, [a.id]: (err.detail as { claimguard: CheckResult }).claimguard }))
          setEditing(a.id)
        }
        toast.error(err instanceof Error ? err.message : "Gagal memproses")
      } finally {
        setBusy(false)
      }
    },
    [items, mutate],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement
      if (t.tagName === "TEXTAREA" || t.tagName === "INPUT" || e.metaKey || e.ctrlKey || e.repeat || busy || konfirmasi) return
      // Di layar sempit detail tersembunyi saat daftar terbuka: jangan memutuskan draf yang tidak terlihat.
      if (!bukaDetail && window.matchMedia("(max-width: 767px)").matches) return
      const k = e.key.toLowerCase()
      if (k === "j") {
        const b = tampil[aktifIdx + 1]
        if (b) setPilihId(b.id)
      } else if (k === "k") {
        const b = tampil[aktifIdx - 1]
        if (b) setPilihId(b.id)
      } else if (!aktif) return
      else if (k === "a" && aktif.draf) setKonfirmasi({ a: aktif, aksi: "setujui" })
      else if (k === "e" && aktif.objek_tipe !== "konten") {
        e.preventDefault()
        setEditing(aktif.id)
      } else if (k === "r") setKonfirmasi({ a: aktif, aksi: "tolak" })
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [tampil, aktif, aktifIdx, busy, konfirmasi, bukaDetail])

  const decided = (history?.items ?? []).filter((a) => a.status !== "menunggu").slice(0, 8)

  return (
    <div>
      <PageHeader
        title="Approval & Eskalasi"
        description="Harga, MOQ, negosiasi, dan klaim kesehatan selalu menunggu keputusan staf. Chat pelanggan dan pesanan tampil lebih dulu."
      />
      {konfirmasi && (
        <KonfirmasiPintas
          a={konfirmasi.a}
          aksi={konfirmasi.aksi}
          onBatal={() => setKonfirmasi(null)}
          onYakin={() => {
            setKonfirmasi(null)
            decide(konfirmasi.a, konfirmasi.aksi)
          }}
        />
      )}
      <div className="panel grid h-[calc(100dvh-16.5rem)] min-h-[520px] grid-rows-[minmax(0,1fr)] overflow-hidden md:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className={cn("min-h-0 flex-col md:flex md:border-r md:border-line", bukaDetail ? "hidden" : "flex")}>
          <div className="space-y-3 border-b p-3">
            <div className="flex gap-1" role="tablist" aria-label="Tampilan approval">
              {(
                [
                  ["antrean", `Menunggu ${items.length}`],
                  ["riwayat", "Baru diputuskan"],
                ] as const
              ).map(([kunci, label]) => (
                <button
                  key={kunci}
                  type="button"
                  role="tab"
                  aria-selected={tab === kunci}
                  onClick={() => setTab(kunci)}
                  className={cn(
                    "h-8 flex-1 rounded-md text-[13px] font-medium transition-colors",
                    tab === kunci ? "bg-soft text-foreground" : "text-muted-foreground hover:bg-soft/70",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            {tab === "antrean" && (
              <>
                <div className="flex gap-2">
                  <label className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-md border border-line bg-white px-2.5">
                    <Search className="size-4 shrink-0 text-subtle-foreground" aria-hidden />
                    <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari toko, alasan, atau draf" className="min-w-0 flex-1 bg-transparent text-[13px] outline-none" aria-label="Cari approval" />
                  </label>
                  <button
                    type="button"
                    onClick={() => setTerbaru((v) => !v)}
                    className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md border border-line bg-white px-2.5 text-[12px] font-medium text-muted-foreground hover:bg-soft"
                    title="Ubah urutan antrean"
                  >
                    <ArrowDownUp className="size-3.5" aria-hidden /> {terbaru ? "Terbaru" : "Terlama"}
                  </button>
                </div>
                <div className="flex flex-wrap gap-1" role="group" aria-label="Filter jenis approval">
                  {FILTER.filter((f) => !f.key || jumlah[f.key]).map((f) => (
                    <button
                      key={f.key}
                      type="button"
                      aria-pressed={filter === f.key}
                      onClick={() => setFilter(f.key)}
                      className={cn(
                        "h-7 rounded-full px-2.5 text-[12px] font-medium transition-colors",
                        filter === f.key ? "bg-primary text-primary-foreground" : "bg-soft text-muted-foreground hover:bg-line",
                      )}
                    >
                      {f.label}
                      {f.key ? <span className="ml-1 opacity-70">{jumlah[f.key]}</span> : null}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
          <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto">
            {tab === "riwayat" ? (
              <ul className="divide-y divide-line">
                {decided.map((a) => (
                  <li key={a.id} className="px-4 py-3 text-[13px]">
                    <div className="flex items-center gap-2">
                      <span className="truncate font-medium">{namaOf(a)}</span>
                      <span
                        className={cn(
                          "ml-auto inline-flex h-5 items-center rounded-md px-1.5 text-[11.5px] font-semibold",
                          a.status === "disetujui" ? "bg-ok-bg text-ok" : "bg-blocked-bg text-blocked",
                        )}
                      >
                        {a.status === "disetujui" ? "Disetujui" : "Ditolak"}
                      </span>
                    </div>
                    <div className="mt-0.5 text-[12px] text-subtle-foreground">
                      {a.ditinjau_oleh} · {relativeTime(a.diputus_pada)}
                    </div>
                  </li>
                ))}
                {decided.length === 0 && <li className="px-4 py-3 text-[13px] text-muted-foreground">Belum ada keputusan.</li>}
              </ul>
            ) : !data ? (
              <SkeletonRows className="p-3" rows={8} />
            ) : tampil.length === 0 ? (
              <EmptyState title={items.length ? "Tidak ada yang cocok" : "Antrean kosong"} description={items.length ? "Coba ubah filter atau kata pencarian." : "Tidak ada draf yang menunggu."} />
            ) : (
              <ul>
                {tampil.map((a) => (
                  <li key={a.id}>
                    <BarisAntrean
                      a={a}
                      dipilih={a.id === aktif?.id}
                      onPilih={() => {
                        setPilihId(a.id)
                        setBukaDetail(true)
                      }}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <div className={cn("min-h-0 md:block", bukaDetail ? "block" : "hidden")}>
          {!data ? (
            <SkeletonRows className="p-4" rows={6} />
          ) : aktif ? (
            <DetailApproval
              key={aktif.id}
              a={aktif}
              editing={editing === aktif.id}
              onEdit={(v) => setEditing(v ? aktif.id : null)}
              onDecide={(aksi, teks) => decide(aktif, aksi, teks)}
              onKembali={() => setBukaDetail(false)}
              busy={busy}
              error={errors[aktif.id] ?? null}
            />
          ) : (
            <div className="flex h-full flex-col">
              <button type="button" onClick={() => setBukaDetail(false)} className="border-b px-4 py-2 text-left text-[13px] text-forest-700 md:hidden">
                ← Semua approval
              </button>
              <EmptyState
                className="flex-1"
                title={items.length ? "Pilih approval" : "Antrean kosong"}
                description={items.length ? "Tidak ada approval yang cocok dengan filter ini." : "Tidak ada draf yang menunggu. AI menangani sisanya dalam batas wewenangnya."}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
