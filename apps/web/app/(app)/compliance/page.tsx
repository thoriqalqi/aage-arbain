"use client"

import { Suspense } from "react"

import { ClaimGuardPlayground } from "@/components/aage/claimguard-playground"
import { SkeletonRows } from "@/components/aage/empty-state"
import { LedgerExplorer } from "@/components/aage/ledger-explorer"
import { PageTabs, usePageTab } from "@/components/aage/page-tabs"
import { PageHeader } from "@/components/aage/panel"

const TABS = ["claimguard", "ledger"] as const

function ComplianceInner() {
  const [tab, setTab] = usePageTab(TABS, "claimguard")
  return (
    <div>
      <PageHeader
        title="Compliance & Ledger"
        description="Tidak ada pesan atau konten yang lolos tanpa ClaimGuard. Aturan deterministik diperiksa lebih dulu, LLM hanya pemeriksa pendukung. Setiap keputusan tercatat di Ledger."
      />
      <PageTabs
        value={tab}
        onChange={setTab}
        items={[
          { value: "claimguard", label: "Pemeriksa klaim" },
          { value: "ledger", label: "Evidence Ledger" },
        ]}
      />
      {tab === "claimguard" ? <ClaimGuardPlayground /> : <LedgerExplorer />}
    </div>
  )
}

export default function CompliancePage() {
  return (
    <Suspense fallback={<SkeletonRows rows={8} />}>
      <ComplianceInner />
    </Suspense>
  )
}
