// Enam agen AAGE (Brief §3). Definisi statis untuk layar Agen, Pengaturan, dan Arsitektur.
// Status & antrean langsung akan diganti data dari GET /api/v1/agents (+ SSE) saat endpoint siap.

export type AutonomyMode = "saran" | "setujui" | "otonom"

export const AUTONOMY_LABEL: Record<AutonomyMode, string> = {
  saran: "Saran saja",
  setujui: "Setujui dulu",
  otonom: "Otonom",
}

export const AUTONOMY_HINT: Record<AutonomyMode, string> = {
  saran: "Agen hanya memberi usulan, staf yang mengeksekusi.",
  setujui: "Agen menyiapkan aksi, staf menyetujui sebelum terkirim.",
  otonom: "Agen bertindak sendiri dalam batas kebijakan.",
}

export type AgentDef = {
  id: string
  nama: string
  singkat: string
  fungsi: string
  prioritas: string
  /** Mode awal pilot — Brief §6.4: mulai dari "Setujui dulu". */
  mode: AutonomyMode
  /** "Otonom" hanya diizinkan untuk jawaban katalog berisiko rendah setelah target akurasi terpenuhi. */
  bolehOtonom: boolean
}

export const AGENTS: AgentDef[] = [
  {
    id: "orchestrator",
    nama: "Orchestrator",
    singkat: "ORC",
    fungsi: "Mengatur alur, memanggil agen, menegakkan mode otonomi dan budget.",
    prioritas: "P0 minimal",
    mode: "setujui",
    bolehOtonom: false,
  },
  {
    id: "opportunity",
    nama: "Opportunity",
    singkat: "OPP",
    fungsi: "Memetakan, menilai, dan memprioritaskan prospek B2B.",
    prioritas: "P0 dasar, P1 lanjutan",
    mode: "saran",
    bolehOtonom: false,
  },
  {
    id: "sales",
    nama: "Sales Assistant",
    singkat: "SAL",
    fungsi: "WhatsApp, info katalog, kualifikasi, draf pesanan, eskalasi.",
    prioritas: "P0",
    mode: "setujui",
    bolehOtonom: true,
  },
  {
    id: "content",
    nama: "Content/Search",
    singkat: "CON",
    fungsi: "Konten pemasaran, SEO, dan kesiapan AI-search.",
    prioritas: "P0 dasar, P1 lanjutan",
    mode: "setujui",
    bolehOtonom: false,
  },
  {
    id: "claimguard",
    nama: "Compliance/ClaimGuard",
    singkat: "CG",
    fungsi: "Memeriksa klaim sebelum terbit atau terkirim.",
    prioritas: "P0",
    mode: "setujui",
    bolehOtonom: false,
  },
  {
    id: "evaluation",
    nama: "Evaluation",
    singkat: "EVA",
    fungsi: "Memantau akurasi, performa, biaya, dan outcome.",
    prioritas: "P1",
    mode: "saran",
    bolehOtonom: false,
  },
]
