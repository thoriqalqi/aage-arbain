"use client"

import { Copy, Link2, ScanSearch, Type } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import useSWR from "swr"

import { AButton } from "@/components/aage/button"
import { ClaimHighlight } from "@/components/aage/claim-highlight"
import { EmptyState } from "@/components/aage/empty-state"
import { Panel, PageHeader, SectionTitle } from "@/components/aage/panel"
import { ScanningBadge, VerdictBadge } from "@/components/aage/status"
import { api, fetcher } from "@/lib/api"
import { formatDuration } from "@/lib/format"
import type { CheckResult, Product } from "@/lib/types"
import { cn } from "@/lib/utils"

const SAMPLE = `Madu Stamina Plus terbukti ampuh menyembuhkan diabetes dan darah tinggi.
Membantu memelihara stamina dan kebugaran tubuh.
Sebanyak 95% pengguna merasakan energi meningkat 3 kali lipat.
100% alami tanpa efek samping.
Produk ini bukan obat dan tidak ditujukan untuk mengobati penyakit.`

export default function ClaimGuardPage() {
  const [mode, setMode] = useState<"teks" | "url">("teks")
  const [text, setText] = useState(SAMPLE)
  const [url, setUrl] = useState("")
  const [productId, setProductId] = useState("")
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<CheckResult | null>(null)
  const { data: products } = useSWR<{ items: Product[] }>("/api/kb/products", fetcher)

  async function check() {
    setLoading(true)
    setResult(null)
    try {
      const res = await api<CheckResult>("/api/claimguard/check", {
        method: "POST",
        json: { text: mode === "teks" ? text : undefined, url: mode === "url" ? url : undefined, product_ids: productId ? [Number(productId)] : undefined },
      })
      setResult(res)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Pemeriksaan gagal")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="ClaimGuard Playground"
        description="Tempel teks atau URL. Setiap kalimat diperiksa 3 tahap: aturan deterministik → pencocokan klaim disetujui → LLM-judge untuk kasus ambigu."
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <Panel className="flex flex-col gap-4 p-5">
          <div className="flex gap-1 self-start rounded-lg bg-soft p-1" role="tablist">
            {(["teks", "url"] as const).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={cn("inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] font-medium", mode === m ? "bg-white shadow-xs" : "text-muted-foreground")}
              >
                {m === "teks" ? <Type className="size-3.5" /> : <Link2 className="size-3.5" />} {m === "teks" ? "Teks" : "URL"}
              </button>
            ))}
          </div>
          {mode === "teks" ? (
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={12}
              className="min-h-64 w-full flex-1 rounded-lg border border-line bg-white p-3 text-[14px] leading-6 outline-none focus:border-blue-500"
              aria-label="Teks yang diperiksa"
            />
          ) : (
            <input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://situs-mitra.co.id/produk/madu"
              className="h-11 w-full rounded-lg border border-line bg-white px-3 outline-none focus:border-blue-500"
              aria-label="URL halaman"
            />
          )}
          <label className="grid gap-1 text-[12px] text-muted-foreground">
            Konteks produk (opsional — untuk mencocokkan klaim disetujui produk tersebut)
            <select value={productId} onChange={(e) => setProductId(e.target.value)} className="h-9 rounded-md border border-line bg-white px-2.5 text-[13px] text-foreground">
              <option value="">Semua produk</option>
              {products?.items.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nama}
                </option>
              ))}
            </select>
          </label>
          <AButton onClick={check} disabled={loading || (mode === "teks" ? !text.trim() : !url.trim())} className="self-start">
            <ScanSearch className="size-4" /> Periksa
          </AButton>
        </Panel>

        <Panel className="p-5">
          <SectionTitle aside={loading ? <ScanningBadge /> : result ? <VerdictBadge verdict={result.verdict} rules={result.rules_triggered} size="md" animate /> : null}>
            Hasil
          </SectionTitle>
          {!result && !loading && <EmptyState title="Belum diperiksa" description="Klik Periksa untuk melihat sorotan merah/kuning/hijau beserta alasannya." />}
          {loading && <div className="shimmer h-48 rounded-lg" />}
          {result && (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-2 text-center">
                {(
                  [
                    ["allowed", "Diizinkan", "bg-ok-bg text-ok"],
                    ["review", "Perlu review", "bg-review-bg text-review"],
                    ["blocked", "Diblokir", "bg-blocked-bg text-blocked"],
                  ] as const
                ).map(([k, label, cls]) => (
                  <div key={k} className={cn("rounded-lg p-2.5", cls)}>
                    <div className="tabular text-2xl font-[650]">{result.summary[k] ?? 0}</div>
                    <div className="text-[12px] font-medium">{label}</div>
                  </div>
                ))}
              </div>
              <div className="rounded-lg border border-line bg-white p-4">
                <ClaimHighlight text={result.text ?? text} result={result} />
              </div>
              <p className="text-[12px] text-subtle-foreground">
                Klik kalimat bersorot untuk melihat aturan dan saran kalimat aman · {formatDuration(result.duration_ms)} · {result.model}
              </p>
              {result.verdict !== "allowed" && (
                <div className="rounded-lg bg-ok-bg/70 p-4">
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="text-[12px] font-semibold tracking-wide text-ok uppercase">Versi aman</span>
                    <AButton
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        navigator.clipboard.writeText(result.safe_text).then(() => toast.success("Versi aman disalin"))
                      }}
                    >
                      <Copy className="size-3.5" /> Salin versi aman
                    </AButton>
                  </div>
                  <p className="leading-6">{result.safe_text}</p>
                </div>
              )}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
