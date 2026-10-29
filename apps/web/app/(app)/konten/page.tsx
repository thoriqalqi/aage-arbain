"use client"

import { Archive, Check, CheckCircle2, Copy, Download, FileSearch, LoaderCircle, Pencil, Send, Sparkles, XCircle } from "lucide-react"
import { motion } from "motion/react"
import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { ClaimHighlight } from "@/components/aage/claim-highlight"
import { EmptyState } from "@/components/aage/empty-state"
import { Panel, PageHeader, SectionTitle, Surface } from "@/components/aage/panel"
import { Pill, ScanningBadge, VerdictBadge } from "@/components/aage/status"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { api, fetcher } from "@/lib/api"
import { formatDateTime } from "@/lib/format"
import type { CheckResult, ContentDraft as BaseDraft, Product, SentenceResult, Verdict } from "@/lib/types"
import { cn } from "@/lib/utils"

const field = "h-10 w-full rounded-md border border-line bg-white px-3 text-[14px] outline-none focus:border-brand-500"

type Draft = Omit<BaseDraft, "tipe" | "status"> & { tipe: string; status: string }
type Report = CheckResult & { json_ld_errors: string[]; sumber_generator: string }
type FormatInfo = { label: string; web: boolean }

const FORMATS: Record<string, FormatInfo> = {
  artikel: { label: "Artikel SEO", web: true },
  deskripsi: { label: "Deskripsi produk (web)", web: true },
  caption_ig: { label: "Caption Instagram", web: false },
  broadcast_wa: { label: "Broadcast WhatsApp (opt-in)", web: false },
  marketplace: { label: "Deskripsi marketplace", web: false },
  brosur: { label: "Brosur grosir apotek", web: false },
}

const STATUS: Record<string, { label: string; cls: string }> = {
  draf: { label: "Draf", cls: "bg-soft text-muted-foreground" },
  menunggu_approval: { label: "Menunggu approval", cls: "bg-escalate-bg text-escalate" },
  disetujui: { label: "Disetujui", cls: "bg-ok-bg text-ok" },
  ditolak: { label: "Ditolak", cls: "bg-blocked-bg text-blocked" },
  diarsipkan: { label: "Diarsipkan", cls: "bg-soft text-subtle-foreground" },
}

function StatusPill({ status }: { status: string }) {
  const s = STATUS[status] ?? STATUS.draf
  return <span className={cn("inline-flex h-6 items-center rounded-full px-2.5 text-[12px] font-medium", s.cls)}>{s.label}</span>
}

function Markdown({ text }: { text: string }) {
  return (
    <div className="space-y-3 leading-7">
      {text.split("\n\n").map((block, i) => {
        const b = block.trim()
        if (b.startsWith("## ")) return <h3 key={i} className="pt-2 text-[17px] font-semibold">{b.slice(3)}</h3>
        if (b.startsWith("|")) {
          const rows = b.split("\n").filter((r) => !/^\|\s*-/.test(r)).map((r) => r.split("|").slice(1, -1).map((c) => c.trim()))
          return (
            <table key={i} className="w-full text-[13px]">
              <tbody>
                {rows.map((r, j) => (
                  <tr key={j} className={cn("border-b border-line", j === 0 && "font-semibold")}>
                    {r.map((c, k) => <td key={k} className="py-1.5 pr-3">{c}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
        if (b.startsWith("- "))
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {b.split("\n").map((l, j) => <li key={j}>{l.replace(/^- /, "")}</li>)}
            </ul>
          )
        const parts = b.split(/(\*\*[^*]+\*\*)/g)
        return (
          <p key={i} className="whitespace-pre-line">
            {parts.map((p, j) => (p.startsWith("**") ? <strong key={j}>{p.slice(2, -2)}</strong> : p))}
          </p>
        )
      })}
    </div>
  )
}

function Step({ n, title, active, done }: { n: number; title: string; active: boolean; done: boolean }) {
  return (
    <div className={cn("flex items-center gap-2 text-[13px]", active ? "font-semibold text-foreground" : "text-muted-foreground")}>
      <span
        className={cn(
          "flex size-6 items-center justify-center rounded-full text-[12px] font-semibold",
          done ? "bg-brand-500 text-white" : active ? "bg-primary text-primary-foreground" : "bg-line",
        )}
      >
        {done ? <Check className="size-3.5" /> : n}
      </span>
      {title}
    </div>
  )
}

/** Teks yang sama dengan yang diperiksa backend (studio.full_text), agar posisi sorotan cocok. */
function reportText(d: Draft) {
  const parts = [d.judul, (d.isi ?? "").replace(/[#*_>|-]+/g, " ")]
  for (const f of d.faq ?? []) parts.push(`${f.q} ${f.a}`)
  parts.push(d.meta?.title ?? "", d.meta?.description ?? "")
  return parts.filter(Boolean).join("\n")
}

/** Editor judul + isi dengan ClaimGuard langsung (deterministik) saat mengetik. */
function DraftEditor({ draft, onSaved, onCancel }: { draft: Draft; onSaved: (d: Draft) => void; onCancel: () => void }) {
  const [judul, setJudul] = useState(draft.judul)
  const [isi, setIsi] = useState(draft.isi ?? "")
  const [live, setLive] = useState<CheckResult | null>(null)
  const [checking, setChecking] = useState(false)
  const [saving, setSaving] = useState(false)
  const text = `${judul}\n${isi}`
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(async () => {
      setChecking(true)
      try {
        setLive(await api<CheckResult>("/api/content/recheck", { method: "POST", json: { teks: text, product_id: draft.product_id } }))
      } catch {
        /* pemeriksaan langsung opsional; simpan tetap memeriksa ulang di server */
      } finally {
        setChecking(false)
      }
    }, 600)
    return () => {
      if (timer.current) clearTimeout(timer.current)
    }
  }, [text, draft.product_id])

  function applySafe(s: SentenceResult) {
    if (!s.suggestion) return
    const target = s.text.trim()
    if (isi.includes(target)) setIsi(isi.replace(target, s.suggestion))
    else if (judul.includes(target)) setJudul(judul.replace(target, s.suggestion))
    toast.success("Kalimat diganti dengan versi aman")
  }

  async function save() {
    setSaving(true)
    try {
      onSaved(await api<Draft>(`/api/content/${draft.id}`, { method: "PATCH", json: { judul, isi } }))
      toast.success("Draf disimpan dan diperiksa ulang ClaimGuard")
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <input value={judul} onChange={(e) => setJudul(e.target.value)} className={cn(field, "font-semibold")} aria-label="Judul" />
      <textarea
        value={isi}
        onChange={(e) => setIsi(e.target.value)}
        rows={12}
        aria-label="Isi konten"
        className="w-full rounded-md border border-line bg-white p-3 font-mono text-[13px] leading-6 outline-none focus:border-brand-500"
      />
      <div className="rounded-lg border border-line bg-canvas p-3">
        <div className="mb-2 flex items-center gap-2 text-[12px] font-medium text-muted-foreground">
          ClaimGuard langsung
          {checking ? <LoaderCircle className="size-3.5 animate-spin" /> : live && <VerdictBadge verdict={live.verdict} rules={live.rules_triggered} />}
          <span className="ml-auto font-normal text-subtle-foreground">Klik kalimat berwarna untuk alasan &amp; versi aman</span>
        </div>
        {live ? <ClaimHighlight text={text} result={live} showAllowed={false} onApply={applySafe} /> : <div className="shimmer h-16 rounded" />}
      </div>
      <div className="flex gap-2">
        <AButton onClick={save} disabled={saving || !judul.trim() || !isi.trim()}>
          {saving ? <LoaderCircle className="size-4 animate-spin" /> : <Check className="size-4" />} Simpan draf
        </AButton>
        <AButton variant="ghost" onClick={onCancel}>
          Batal
        </AButton>
      </div>
    </div>
  )
}

function Studio() {
  const { data: products } = useSWR<{ items: Product[] }>("/api/kb/products", fetcher)
  const { data: list, mutate: mutateList } = useSWR<{ items: Draft[]; format?: Record<string, FormatInfo> }>("/api/content", fetcher)
  const formats = list?.format ?? FORMATS
  const [productId, setProductId] = useState("")
  const [topik, setTopik] = useState("")
  const [target, setTarget] = useState<"apotek" | "konsumen">("apotek")
  const [tipe, setTipe] = useState("artikel")
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [elapsed, setElapsed] = useState<number | null>(null)
  const topikOk = (topik.match(/[A-Za-z]/g)?.length ?? 0) >= 3

  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id")
    if (id) open(Number(id))
  }, [])

  async function generate() {
    if (!productId) return toast.error("Pilih produk terlebih dahulu")
    if (!topikOk) return toast.error("Isi topik minimal 3 huruf, mis. 'stamina saat musim hujan'")
    setLoading(true)
    setEditing(false)
    const t = performance.now()
    try {
      const d = await api<Draft>("/api/content/generate", { method: "POST", json: { product_id: Number(productId), topik, target, tipe } })
      setDraft(d)
      setElapsed(performance.now() - t)
      mutateList()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Gagal membuat draf")
    } finally {
      setLoading(false)
    }
  }

  async function act(path: string, ok: string) {
    if (!draft) return
    setBusy(true)
    try {
      setDraft(await api<Draft>(`/api/content/${draft.id}/${path}`, { method: "POST" }))
      toast.success(ok)
      mutateList()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Gagal memproses")
    } finally {
      setBusy(false)
    }
  }

  async function exportDraft() {
    if (!draft) return
    try {
      const res = await api<{ format: "html" | "teks"; html?: string; teks?: string }>(`/api/content/${draft.id}/export`)
      const body = res.format === "html" ? res.html! : res.teks!
      if (res.format === "teks") await navigator.clipboard?.writeText(body).catch(() => undefined)
      const blob = new Blob([body], { type: res.format === "html" ? "text/html" : "text/plain" })
      const a = document.createElement("a")
      a.href = URL.createObjectURL(blob)
      a.download = `konten-${draft.id}.${res.format === "html" ? "html" : "txt"}`
      a.click()
      URL.revokeObjectURL(a.href)
      toast.success(res.format === "html" ? "HTML + JSON-LD diekspor" : "Teks disalin ke clipboard dan diunduh")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Ekspor ditolak")
    }
  }

  async function open(id: number) {
    setEditing(false)
    setDraft(await api<Draft>(`/api/content/${id}`))
    setElapsed(null)
  }

  const report = draft?.claim_report as Report | undefined
  const fmt = draft ? (formats[draft.tipe] ?? { label: draft.tipe, web: true }) : null
  const step = !draft ? 1 : draft.status === "disetujui" ? 3 : 2
  const canEdit = draft && ["draf", "ditolak", "disetujui"].includes(draft.status)
  const blocked = draft?.claim_verdict === "blocked"

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
      <div className="space-y-4">
        <div className="flex flex-wrap gap-5">
          <Step n={1} title="Produk & topik" active={step === 1} done={step > 1} />
          <Step n={2} title="Edit & ajukan" active={step === 2} done={step > 2} />
          <Step n={3} title="Disetujui & ekspor" active={step === 3} done={false} />
        </div>
        <Panel className="grid gap-4 p-5 md:grid-cols-2">
          <label className="grid gap-1 text-[12px] text-muted-foreground">
            Produk
            <select value={productId} onChange={(e) => setProductId(e.target.value)} className={field}>
              <option value="">Pilih produk…</option>
              {products?.items.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nama}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-[12px] text-muted-foreground">
            Topik / kata kunci <span className="text-subtle-foreground">(wajib)</span>
            <input
              value={topik}
              onChange={(e) => setTopik(e.target.value)}
              placeholder="mis. stamina saat musim hujan"
              className={cn(field, topik && !topikOk && "border-review")}
            />
          </label>
          <label className="grid gap-1 text-[12px] text-muted-foreground">
            Target pembaca
            <select value={target} onChange={(e) => setTarget(e.target.value as "apotek")} className={field}>
              <option value="apotek">Apotek & toko obat</option>
              <option value="konsumen">Konsumen</option>
            </select>
          </label>
          <label className="grid gap-1 text-[12px] text-muted-foreground">
            Format
            <select value={tipe} onChange={(e) => setTipe(e.target.value)} className={field}>
              {Object.entries(formats).map(([k, v]) => (
                <option key={k} value={k}>
                  {v.label}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-wrap items-center gap-3 md:col-span-2">
            <AButton onClick={generate} disabled={loading || !productId || !topikOk}>
              {loading ? <LoaderCircle className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
              {formats[tipe]?.web ? "Buat draf + FAQ + JSON-LD" : "Buat draf"}
            </AButton>
            <span className="text-[12px] text-subtle-foreground">Fakta hanya dari katalog & klaim yang disetujui. Semua draf diperiksa ClaimGuard.</span>
          </div>
        </Panel>

        {loading && <div className="shimmer h-72 rounded-xl" />}
        {draft && !loading && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24 }}>
            <Panel className="p-5">
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <h2 className="mr-auto text-lg font-semibold">{draft.judul}</h2>
                {fmt && <Pill>{fmt.label}</Pill>}
                {elapsed != null && <Pill>selesai {(elapsed / 1000).toFixed(1).replace(".", ",")} dtk</Pill>}
                {report && <Pill>generator: {report.sumber_generator}</Pill>}
                <StatusPill status={draft.status} />
                <VerdictBadge verdict={draft.claim_verdict} rules={report?.rules_triggered} size="md" animate />
              </div>

              {editing ? (
                <DraftEditor
                  key={draft.id}
                  draft={draft}
                  onCancel={() => setEditing(false)}
                  onSaved={(d) => {
                    setDraft(d)
                    setEditing(false)
                    mutateList()
                  }}
                />
              ) : (
                <Tabs defaultValue="isi" key={draft.id}>
                  <TabsList>
                    <TabsTrigger value="isi">Isi</TabsTrigger>
                    {fmt?.web && <TabsTrigger value="faq">FAQ</TabsTrigger>}
                    {fmt?.web && <TabsTrigger value="jsonld">JSON-LD</TabsTrigger>}
                    {fmt?.web && <TabsTrigger value="meta">Meta</TabsTrigger>}
                    <TabsTrigger value="claimguard">ClaimGuard</TabsTrigger>
                  </TabsList>
                  <TabsContent value="isi" className="pt-3">
                    <Markdown text={draft.isi ?? ""} />
                  </TabsContent>
                  <TabsContent value="faq" className="space-y-3 pt-3">
                    {draft.faq?.map((f) => (
                      <div key={f.q} className="rounded-lg border border-line bg-white p-3">
                        <div className="font-semibold">{f.q}</div>
                        <p className="mt-1 text-muted-foreground">{f.a}</p>
                      </div>
                    ))}
                  </TabsContent>
                  <TabsContent value="jsonld" className="pt-3">
                    <div className="mb-2 flex items-center gap-2 text-[13px]">
                      {report?.json_ld_errors?.length ? (
                        <span className="inline-flex items-center gap-1 text-blocked"><XCircle className="size-4" /> {report.json_ld_errors.join("; ")}</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-ok"><CheckCircle2 className="size-4" /> Sintaks JSON-LD valid (Product, FAQPage, Organization)</span>
                      )}
                    </div>
                    <pre className="scrollbar-thin max-h-96 overflow-auto rounded-lg bg-forest-950 p-4 font-mono text-[12px] leading-[18px] text-brand-300">
                      {JSON.stringify(draft.json_ld, null, 2)}
                    </pre>
                  </TabsContent>
                  <TabsContent value="meta" className="space-y-3 pt-3">
                    <div className="rounded-lg border border-line bg-white p-4">
                      <div className="text-[12px] text-subtle-foreground">Pratinjau hasil pencarian</div>
                      <div className="mt-1 text-[17px] text-info">{draft.meta?.title}</div>
                      <div className="text-[13px] text-ok">arbain.co.id › produk</div>
                      <div className="text-[13px] text-muted-foreground">{draft.meta?.description}</div>
                    </div>
                    <div className="text-[12px] text-muted-foreground">
                      Title {draft.meta?.title?.length ?? 0}/60 karakter · Description {draft.meta?.description?.length ?? 0}/155 karakter
                    </div>
                  </TabsContent>
                  <TabsContent value="claimguard" className="pt-3">
                    {report && <ClaimHighlight text={reportText(draft)} result={report} />}
                  </TabsContent>
                </Tabs>
              )}

              {!editing && (
                <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-line pt-4">
                  {(draft.status === "draf" || draft.status === "ditolak") && (
                    <AButton onClick={() => act("submit", "Diajukan ke antrean Approval")} disabled={busy || blocked}>
                      <Send className="size-4" /> Ajukan ke Approval
                    </AButton>
                  )}
                  {draft.status === "disetujui" && (
                    <AButton onClick={exportDraft}>
                      {fmt?.web ? <Download className="size-4" /> : <Copy className="size-4" />}
                      {fmt?.web ? "Ekspor HTML + JSON-LD" : "Salin & unduh teks"}
                    </AButton>
                  )}
                  {draft.status === "menunggu_approval" && (
                    <Link href="/approval" className="btn-glass inline-flex h-9 items-center gap-1.5 rounded-[10px] px-3 text-[13px] font-medium">
                      Buka antrean Approval
                    </Link>
                  )}
                  {canEdit && (
                    <AButton variant="outline" onClick={() => setEditing(true)} disabled={busy}>
                      <Pencil className="size-4" /> Edit
                    </AButton>
                  )}
                  {draft.status !== "diarsipkan" && (
                    <AButton variant="ghost" onClick={() => act("arsip", "Draf diarsipkan")} disabled={busy}>
                      <Archive className="size-4" /> Arsipkan
                    </AButton>
                  )}
                  <span className="text-[12px] text-muted-foreground">
                    {blocked
                      ? "Diblokir ClaimGuard: edit kalimat bertanda merah sebelum diajukan."
                      : draft.status === "menunggu_approval"
                        ? "Menunggu persetujuan staf lain. Pembuat tidak boleh menyetujui drafnya sendiri."
                        : draft.status === "disetujui"
                          ? "Disetujui lewat Approval. Mengedit akan membuatnya perlu disetujui ulang."
                          : draft.status === "ditolak"
                            ? "Ditolak penyetuju. Edit lalu ajukan ulang."
                            : "Ekspor hanya setelah disetujui staf lain di menu Approval."}
                  </span>
                </div>
              )}
            </Panel>
          </motion.div>
        )}
      </div>
      <aside>
        <Panel className="overflow-hidden">
          <div className="border-b border-line px-4 py-3.5 text-[14.5px] font-semibold">Draf terbaru</div>
          <ul className="divide-y divide-line">
            {list?.items.slice(0, 12).map((d) => (
              <li key={d.id}>
                <button onClick={() => open(d.id)} className={cn("w-full px-4 py-3 text-left text-[13px] hover:bg-brand-50", draft?.id === d.id && "bg-brand-50")}>
                  <div className="line-clamp-1 font-medium">{d.judul}</div>
                  <div className="mt-0.5 text-[11.5px] text-subtle-foreground">{formats[d.tipe]?.label ?? d.tipe}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5">
                    <VerdictBadge verdict={d.claim_verdict as Verdict} />
                    <StatusPill status={d.status} />
                    <span className="text-[11.5px] text-subtle-foreground">{formatDateTime(d.dibuat_pada)}</span>
                  </div>
                </button>
              </li>
            ))}
            {list?.items.length === 0 && <li className="px-4 py-3 text-[13px] text-muted-foreground">Belum ada draf.</li>}
          </ul>
        </Panel>
      </aside>
    </div>
  )
}

type AuditReport = {
  sumber: string
  skor_sebelum: number
  skor_sesudah: number
  cek: { id: string; label: string; status: "lulus" | "gagal"; bobot: number; detail: string; saran: string }[]
  perbaikan_kalimat: { sebelum: string; sesudah: string; verdict: Verdict; aturan: string[] }[]
  ringkasan: { kalimat: number; berisiko: number; diblokir: number; statistik_tanpa_sumber: number }
}

function Audit() {
  const [url, setUrl] = useState("")
  const [loading, setLoading] = useState(false)
  const [rep, setRep] = useState<AuditReport | null>(null)
  async function run(contoh: boolean) {
    setLoading(true)
    try {
      setRep(await api<AuditReport>("/api/content/audit", { method: "POST", json: contoh ? { contoh: true } : { url } }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Audit gagal")
    } finally {
      setLoading(false)
    }
  }
  return (
    <div className="space-y-4">
      <Panel className="flex flex-wrap items-end gap-3 p-5">
        <label className="grid min-w-64 flex-1 gap-1 text-[12px] text-muted-foreground">
          URL halaman situs mitra
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" className={field} />
        </label>
        <AButton onClick={() => run(false)} disabled={loading || !url}>
          <FileSearch className="size-4" /> Audit
        </AButton>
        <AButton variant="outline" onClick={() => run(true)} disabled={loading}>
          Pakai halaman contoh
        </AButton>
      </Panel>
      {loading && <ScanningBadge />}
      {!rep && !loading && <Surface><EmptyState title="Belum ada audit" description="Masukkan URL (dengan izin mitra) atau pakai halaman contoh untuk demo." /></Surface>}
      {rep && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <Panel className="p-5">
              <div className="text-[12px] font-medium text-muted-foreground">Sebelum</div>
              <div className="tabular text-[40px] leading-[48px] font-[650] text-blocked">{rep.skor_sebelum}</div>
              <p className="text-[13px] text-muted-foreground">
                {rep.ringkasan.berisiko} dari {rep.ringkasan.kalimat} kalimat berisiko · {rep.ringkasan.diblokir} diblokir ·{" "}
                {rep.ringkasan.statistik_tanpa_sumber} statistik tanpa sumber
              </p>
            </Panel>
            <Panel className="p-5">
              <div className="text-[12px] font-medium text-muted-foreground">Sesudah (saran diterapkan)</div>
              <div className="tabular text-[40px] leading-[48px] font-[650] text-ok">{rep.skor_sesudah}</div>
              <p className="text-[13px] text-muted-foreground">Kalimat diganti klaim disetujui + meta, heading, FAQ, dan JSON-LD dari Studio.</p>
            </Panel>
          </div>
          <Surface className="divide-y divide-line">
            {rep.cek.map((c) => (
              <div key={c.id} className="flex items-start gap-3 p-4">
                {c.status === "lulus" ? <CheckCircle2 className="mt-0.5 size-5 text-ok" /> : <XCircle className="mt-0.5 size-5 text-blocked" />}
                <div className="min-w-0 flex-1">
                  <div className="font-medium">{c.label} <span className="text-[12px] font-normal text-subtle-foreground">· bobot {c.bobot}</span></div>
                  <div className="text-[13px] text-muted-foreground">{c.detail}</div>
                  {c.status === "gagal" && <div className="text-[13px] text-forest-700">Saran: {c.saran}</div>}
                </div>
              </div>
            ))}
          </Surface>
          {rep.perbaikan_kalimat.length > 0 && (
            <div>
              <SectionTitle>Kalimat sebelum → sesudah</SectionTitle>
              <div className="space-y-3">
                {rep.perbaikan_kalimat.map((p, i) => (
                  <div key={i} className="grid gap-2 md:grid-cols-2">
                    <div className="rounded-lg bg-blocked-bg/60 p-3 text-[13px]">
                      <div className="mb-1 flex items-center gap-2"><VerdictBadge verdict={p.verdict} rules={p.aturan} /></div>
                      <span className={p.verdict === "blocked" ? "mark-blocked" : "mark-review"}>{p.sebelum}</span>
                    </div>
                    <div className="rounded-lg bg-ok-bg/70 p-3 text-[13px]">
                      <div className="mb-1"><VerdictBadge verdict="allowed" /></div>
                      {p.sesudah}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default function KontenPage() {
  return (
    <div>
      <PageHeader
        title="Studio Konten"
        description="Konten jujur untuk web, Instagram, WhatsApp, marketplace, dan brosur apotek. Semua fakta dari katalog, wajib lolos ClaimGuard, dan terbit lewat Approval."
      />
      <Tabs defaultValue="studio">
        <TabsList className="mb-4">
          <TabsTrigger value="studio">Studio konten</TabsTrigger>
          <TabsTrigger value="audit">Audit halaman</TabsTrigger>
        </TabsList>
        <TabsContent value="studio">
          <Studio />
        </TabsContent>
        <TabsContent value="audit">
          <Audit />
        </TabsContent>
      </Tabs>
    </div>
  )
}
