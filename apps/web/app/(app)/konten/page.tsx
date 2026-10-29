"use client"

import { Check, CheckCircle2, Download, FileSearch, LoaderCircle, Sparkles, XCircle } from "lucide-react"
import { motion } from "motion/react"
import { useState } from "react"
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
import type { CheckResult, ContentDraft, Product, Verdict } from "@/lib/types"
import { cn } from "@/lib/utils"

const field = "h-10 w-full rounded-md border border-line bg-white px-3 text-[14px] outline-none focus:border-brand-500"

function Markdown({ text }: { text: string }) {
  return (
    <div className="space-y-3 leading-7">
      {text.split("\n\n").map((block, i) => {
        const b = block.trim()
        if (b.startsWith("## ")) return <h3 key={i} className="pt-2 text-[17px] font-semibold">{b.slice(3)}</h3>
        if (b.startsWith("- "))
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {b.split("\n").map((l, j) => <li key={j}>{l.replace(/^- /, "")}</li>)}
            </ul>
          )
        const parts = b.split(/(\*\*[^*]+\*\*)/g)
        return (
          <p key={i}>
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

function Studio() {
  const { data: products } = useSWR<{ items: Product[] }>("/api/kb/products", fetcher)
  const { data: list, mutate: mutateList } = useSWR<{ items: ContentDraft[] }>("/api/content", fetcher)
  const [productId, setProductId] = useState("")
  const [topik, setTopik] = useState("")
  const [target, setTarget] = useState<"apotek" | "konsumen">("apotek")
  const [tipe, setTipe] = useState<"artikel" | "deskripsi">("artikel")
  const [loading, setLoading] = useState(false)
  const [draft, setDraft] = useState<ContentDraft | null>(null)
  const [elapsed, setElapsed] = useState<number | null>(null)

  async function generate() {
    if (!productId) return toast.error("Pilih produk terlebih dahulu")
    setLoading(true)
    const t = performance.now()
    try {
      const d = await api<ContentDraft>("/api/content/generate", { method: "POST", json: { product_id: Number(productId), topik, target, tipe } })
      setDraft(d)
      setElapsed(performance.now() - t)
      mutateList()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Gagal membuat draf")
    } finally {
      setLoading(false)
    }
  }

  async function approve() {
    if (!draft) return
    try {
      setDraft(await api<ContentDraft>(`/api/content/${draft.id}/approve`, { method: "POST" }))
      toast.success("Konten disetujui — siap diekspor")
      mutateList()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Gagal menyetujui")
    }
  }

  async function exportDraft() {
    if (!draft) return
    try {
      const res = await api<{ html: string }>(`/api/content/${draft.id}/export`)
      const blob = new Blob([res.html], { type: "text/html" })
      const a = document.createElement("a")
      a.href = URL.createObjectURL(blob)
      a.download = `konten-${draft.id}.html`
      a.click()
      URL.revokeObjectURL(a.href)
      toast.success("HTML + JSON-LD diekspor")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Ekspor ditolak")
    }
  }

  async function open(id: number) {
    setDraft(await api<ContentDraft>(`/api/content/${id}`))
    setElapsed(null)
  }

  const report = draft?.claim_report as (CheckResult & { json_ld_errors: string[]; sumber_generator: string }) | undefined
  const step = !draft ? 1 : draft.status === "disetujui" ? 3 : 2
  const fullText = draft ? reportText(draft) : ""

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_300px]">
      <div className="space-y-4">
        <div className="flex flex-wrap gap-5">
          <Step n={1} title="Produk & topik" active={step === 1} done={step > 1} />
          <Step n={2} title="Pratinjau draf" active={step === 2} done={step > 2} />
          <Step n={3} title="Verdict & ekspor" active={step === 3} done={false} />
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
            Topik / kata kunci
            <input value={topik} onChange={(e) => setTopik(e.target.value)} placeholder="mis. madu untuk stamina pelanggan apotek" className={field} />
          </label>
          <label className="grid gap-1 text-[12px] text-muted-foreground">
            Target pembaca
            <select value={target} onChange={(e) => setTarget(e.target.value as "apotek")} className={field}>
              <option value="apotek">Apotek & toko obat</option>
              <option value="konsumen">Konsumen</option>
            </select>
          </label>
          <label className="grid gap-1 text-[12px] text-muted-foreground">
            Jenis
            <select value={tipe} onChange={(e) => setTipe(e.target.value as "artikel")} className={field}>
              <option value="artikel">Artikel</option>
              <option value="deskripsi">Deskripsi produk</option>
            </select>
          </label>
          <div className="md:col-span-2">
            <AButton onClick={generate} disabled={loading}>
              {loading ? <LoaderCircle className="size-4 animate-spin" /> : <Sparkles className="size-4" />} Buat draf + FAQ + JSON-LD
            </AButton>
          </div>
        </Panel>

        {loading && <div className="shimmer h-72 rounded-xl" />}
        {draft && !loading && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24 }}>
            <Panel className="p-5">
              <div className="mb-4 flex flex-wrap items-center gap-2">
                <h2 className="mr-auto text-lg font-semibold">{draft.judul}</h2>
                {elapsed != null && <Pill>selesai {(elapsed / 1000).toFixed(1).replace(".", ",")} dtk</Pill>}
                {report && <Pill>generator: {report.sumber_generator}</Pill>}
                <VerdictBadge verdict={draft.claim_verdict} rules={report?.rules_triggered} size="md" animate />
              </div>
              <Tabs defaultValue="artikel">
                <TabsList>
                  <TabsTrigger value="artikel">{draft.tipe === "artikel" ? "Artikel" : "Deskripsi"}</TabsTrigger>
                  <TabsTrigger value="faq">FAQ</TabsTrigger>
                  <TabsTrigger value="jsonld">JSON-LD</TabsTrigger>
                  <TabsTrigger value="meta">Meta</TabsTrigger>
                  <TabsTrigger value="claimguard">ClaimGuard</TabsTrigger>
                </TabsList>
                <TabsContent value="artikel" className="pt-3">
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
                  {report && <ClaimHighlight text={fullText} result={report} />}
                </TabsContent>
              </Tabs>
              <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-line pt-4">
                {draft.status !== "disetujui" ? (
                  <AButton onClick={approve} disabled={draft.claim_verdict === "blocked"}>
                    <Check className="size-4" /> Setujui konten
                  </AButton>
                ) : (
                  <AButton onClick={exportDraft}>
                    <Download className="size-4" /> Ekspor HTML + JSON-LD
                  </AButton>
                )}
                <span className="text-[12px] text-muted-foreground">
                  {draft.claim_verdict === "blocked"
                    ? "Draf Diblokir ClaimGuard tidak dapat disetujui atau diekspor."
                    : draft.status === "disetujui"
                      ? "Disetujui staf — ekspor diizinkan."
                      : "Ekspor hanya setelah staf menyetujui."}
                </span>
              </div>
            </Panel>
          </motion.div>
        )}
      </div>
      <aside>
        <Panel className="overflow-hidden">
          <div className="border-b border-line px-4 py-3.5 text-[14.5px] font-semibold">Draf terbaru</div>
          <ul className="divide-y divide-line">
            {list?.items.slice(0, 10).map((d) => (
              <li key={d.id}>
                <button onClick={() => open(d.id)} className={cn("w-full px-4 py-3 text-left text-[13px] hover:bg-brand-50", draft?.id === d.id && "bg-brand-50")}>
                  <div className="line-clamp-1 font-medium">{d.judul}</div>
                  <div className="mt-1 flex items-center gap-2">
                    <VerdictBadge verdict={d.claim_verdict as Verdict} />
                    <span className="text-[11.5px] text-subtle-foreground">{d.status} · {formatDateTime(d.dibuat_pada)}</span>
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

function reportText(d: ContentDraft) {
  // Teks yang sama dengan yang diperiksa backend (studio.full_text)
  const parts = [d.judul, (d.isi ?? "").replace(/[#*_>-]+/g, " ")]
  for (const f of d.faq ?? []) parts.push(`${f.q} ${f.a}`)
  parts.push(d.meta?.title ?? "", d.meta?.description ?? "")
  return parts.join("\n")
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
        description="Draf artikel dan deskripsi bersumber untuk SEO dan AI-search. Tanpa janji ranking, tanpa statistik tanpa sumber, dan wajib lolos ClaimGuard."
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
