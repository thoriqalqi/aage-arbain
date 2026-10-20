export type Verdict = "allowed" | "review" | "blocked"

export type Source = {
  jenis?: string
  chunk_id?: number
  document_id?: number
  judul?: string
  versi?: number
  halaman?: number | null
  product_id?: number | null
  skor?: number
  kutipan?: string
  approval_id?: number
  order_draft_id?: number
}

export type Message = {
  id: number
  arah: "masuk" | "keluar"
  pengirim: "pembeli" | "ai" | "staf"
  teks: string
  status_kirim: string
  verdict: Verdict | null
  verdict_label: string | null
  sumber: Source[]
  biaya_rp: number
  trace_id: string | null
  waktu: string
}

export type Contact = {
  id: number
  wa_number: string
  nama_toko: string | null
  tipe_toko: string | null
  alamat: string | null
  opt_in: boolean
}

export type ConversationSummary = {
  id: number
  kanal: "whatsapp" | "webchat"
  status: "otomatis" | "eskalasi" | "ditahan"
  intent_terakhir: string | null
  diperbarui_pada: string
  contact: Contact
  pesan_terakhir: Message | null
  approval_menunggu: number
}

export type LedgerEvent = {
  id: number
  waktu: string
  tipe_event: string
  trace_id: string | null
  conversation_id: number | null
  product_id: number | null
  objek_ref: string | null
  sumber_ref: Source[]
  ringkasan: string
  alasan: string
  verdict: Verdict | null
  verdict_label: string | null
  aturan_terpicu: string[]
  model: string | null
  token_in: number
  token_out: number
  biaya_rp: number
  latensi_ms: number | null
  aktor: string
  outcome: string | null
  data: Record<string, unknown>
}

export type Approval = {
  id: number
  objek_tipe: "balasan" | "order_draft" | "konten" | "agen_negosiasi" | "agen_deal_final" | "agen_konten"
  objek_id: number | null
  conversation_id: number | null
  alasan: string
  ringkasan: string
  intent: string | null
  draf: string
  verdict: Verdict | null
  verdict_label: string | null
  status: "menunggu" | "disetujui" | "ditolak"
  ditinjau_oleh: string | null
  catatan: string | null
  trace_id: string | null
  dibuat_pada: string
  diputus_pada: string | null
  contact: Contact | null
}

export type OrderDraft = {
  id: number
  item: { sku: string; nama: string; qty: number; satuan: string; subtotal: number; diskon_persen: number }[]
  nama_toko: string | null
  alamat: string | null
  total: number
  status: string
  dibuat_pada: string
}

export type ConversationDetail = ConversationSummary & {
  pesan: Message[]
  ledger: LedgerEvent[]
  biaya_total_rp: number
  pesanan_terakhir: OrderDraft | null
  approvals: Approval[]
  konteks: Record<string, unknown>
}

export type RuleHit = { id: string; label: string; severity: Verdict; match: string; alasan: string }

export type SentenceResult = {
  text: string
  start: number
  end: number
  verdict: Verdict
  rules: RuleHit[]
  reasons: string[]
  matched_claim: { id: number; teks: string; product_id: number; skor: number; sumber: string } | null
  suggestion: string | null
  stage: string
}

export type CheckResult = {
  verdict: Verdict
  label: string
  sentences: SentenceResult[]
  rules_triggered: string[]
  summary: Record<Verdict, number>
  safe_text: string
  model: string
  biaya_rp: number
  duration_ms: number
  text?: string
}

export type Product = {
  id: number
  sku: string
  nama: string
  kategori: string
  komposisi: string
  kemasan: string
  satuan_grosir: string
  no_izin_edar: string
  harga_dasar: number
  moq: number
  sumber_data: string
  aktif: boolean
  klaim: { id: number; teks: string; sumber: string; diverifikasi_oleh: string | null }[]
  tier: { min_qty: number; diskon_maks_persen: number }[]
}

export type ContentDraft = {
  id: number
  product_id: number | null
  tipe: "artikel" | "deskripsi"
  topik: string
  target: string
  judul: string
  claim_verdict: Verdict
  verdict_label: string
  status: "draf" | "disetujui" | "ditolak"
  dibuat_pada: string
  isi?: string
  faq?: { q: string; a: string }[]
  meta?: { title?: string; description?: string }
  json_ld?: Record<string, unknown>[]
  claim_report?: CheckResult & { json_ld_errors: string[]; sumber_generator: string }
}

export type ScoreReason = { faktor: string; poin: number; maks: number; keterangan: string }

export type Prospect = {
  id: number
  nama: string
  alamat: string
  wilayah: string
  lat: number | null
  lng: number | null
  tipe: string
  telepon: string | null
  website: string | null
  rating: number | null
  jumlah_ulasan: number | null
  jarak_km: number | null
  sudah_pelanggan: boolean
  skor: number
  alasan_skor: ScoreReason[]
  draf_pesan: string
  draf_verdict: Verdict | null
  status: "baru" | "dihubungi" | "merespons" | "menolak"
  sumber: string
  osm_id: string | null
  jam_buka: string | null
  alamat_jalan_ada: boolean
  skor_geo: number
  skor_data: number
  terakhir_dipindai: string | null
}

export type Kpi = {
  ringkasan: {
    chat: number
    pesan_masuk: number
    otomatis_persen: number
    eskalasi_persen: number
    keputusan: Record<string, number>
    klaim_diblokir: number
    klaim_ditahan: number
    respons_ai_rata_ms: number | null
    respons_ai_p95_ms: number | null
    respons_staf_rata_menit: number | null
    biaya_total_rp: number
    biaya_per_percakapan_rp: number
  }
  delta: Record<string, number | null>
  harian: {
    tanggal: string
    chat: number
    pesan: number
    otomatis: number
    eskalasi: number
    diblokir: number
    biaya_per_percakapan_rp: number
    otomatis_persen: number
  }[]
  funnel: { tahap: string; nilai: number; konversi_persen: number | null }[]
  biaya_bulan_ini_rp: number
}

export type Status = {
  llm: { aktif: boolean; model: string; judge: string | null }
  whatsapp: { aktif: boolean; kanal_cadangan: string }
  prospek: { google_places: boolean; osm: boolean }
  anggaran: { harian_rp: number; bulanan_rp: number; terpakai_hari_ini_rp: number; terpakai_bulan_ini_rp: number }
}

export const INTENT_LABEL: Record<string, string> = {
  salam: "Salam",
  tanya_produk: "Tanya produk",
  izin_edar: "Izin edar",
  harga_moq: "Harga & MOQ",
  negosiasi: "Negosiasi",
  pesan: "Pesan",
  pesan_ulang: "Pesan ulang",
  klaim_kesehatan: "Klaim kesehatan",
  medis_personal: "Medis personal",
  keluhan: "Keluhan",
  minta_staf: "Minta staf",
  kebijakan: "Kebijakan",
  lainnya: "Lainnya",
}
