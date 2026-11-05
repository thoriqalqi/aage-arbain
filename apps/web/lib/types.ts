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

export type Channel = "whatsapp" | "telegram" | "webchat"

export type Contact = {
  id: number
  channel: Channel
  external_user_id: string
  wa_number: string | null
  nama_toko: string | null
  nama_wa: string | null
  tipe_toko: string | null
  alamat: string | null
  opt_in: boolean
  prospect_id: number | null
}

export type ConversationSummary = {
  id: number
  kanal: Channel
  status: "otomatis" | "eskalasi" | "ditahan" | "ditangani_staf"
  intent_terakhir: string | null
  diperbarui_pada: string
  contact: Contact
  pesan_terakhir: Message | null
  approval_menunggu: number
  menunggu_sejak: string | null
  ditangani_oleh: string | null
  ditangani_sejak: string | null
  aktivitas_staf_terakhir: string | null
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
  /** Ringkasan percakapan yang disusun aturan (produk, jumlah, kebutuhan, keberatan, tahap). Kosong bila belum ada. */
  memori: string
  saran_ai: { teks: string | null; verdict: Verdict | null; intent: string; catatan: string | null; waktu: string } | null
  jendela: { berlaku: boolean; terbuka: boolean; berakhir: string | null; jam: number | null }
  prospek: { id: number; nama: string; status: string; skor: number } | null
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

export type StatusVerifikasi = "terverifikasi" | "simulasi" | "belum_diverifikasi" | "kedaluwarsa"

export type FaktaVerifikasi = {
  objek_tipe: "produk" | "klaim" | "dokumen"
  objek_id: number
  jenis_fakta: string
  label: string
  nilai: string
  status: StatusVerifikasi
  nilai_berubah: boolean
  diverifikasi_oleh: string | null
  diverifikasi_pada: string | null
  sumber_bukti: string | null
  berlaku_sampai: string | null
  produk: { id: number; sku: string; nama: string } | null
}

export type VerifikasiDaftar = {
  mode_data: "produksi" | "demo"
  ringkasan: Record<StatusVerifikasi, number>
  items: FaktaVerifikasi[]
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
  stok: number | null
  deskripsi: string
  halal: string | null
  bko: string | null
  klaim: { id: number; teks: string; sumber: string; diverifikasi_oleh: string | null; status_verifikasi?: StatusVerifikasi }[]
  tier: { min_qty: number; diskon_maks_persen: number }[]
  verifikasi?: { terlemah: StatusVerifikasi; per_fakta: Record<string, StatusVerifikasi> }
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
  status: "baru" | "dihubungi" | "merespons" | "pelanggan" | "menolak"
  wa: string | null
  ada_wa: boolean
  consent_status: "UNKNOWN" | "GRANTED" | "OPTED_OUT"
  consent_sumber: string | null
  consent_cakupan: string | null
  consent_pada: string | null
  skor_versi: string | null
  confidence: number | null
  verifikasi: string
  dikumpulkan_pada: string | null
  diperbarui_pada: string | null
  conversation_id: number | null
  catatan: string | null
  tindak_lanjut_pada: string | null
  pic: string | null
  jaringan: string | null
  sumber: string
  osm_id: string | null
  jam_buka: string | null
  alamat_jalan_ada: boolean
  skor_geo: number
  skor_data: number
  terakhir_dipindai: string | null
  market_analysis: MarketAnalysis | null
  nba: NextBestAction | null
  terakhir_diverifikasi: string | null
  digabung_ke_id: number | null
  sumber_label: string
  skor_sementara: boolean
  status_verifikasi: "belum" | "perlu_tinjauan" | "terverifikasi" | "ditolak"
  alasan_tinjauan: string[]
  langkah_berikutnya: string
}

export type DaftarLead = {
  items: Prospect[]
  total: number
  wilayah: string[]
  jenis_toko: string[]
  segmen: string[]
  sumber_opsi: Record<string, string>
  pindaian_latar: boolean
  gudang: { nama: string; lat: number; lng: number }
}

export type KesalahanLead = { kolom: string; alasan: string; baris?: number }
export type AlasanDuplikat = { aturan: string; keterangan: string }

export type LeadRingkas = {
  id: number
  nama: string
  alamat: string
  wilayah: string
  tipe: string
  telepon: string | null
  skor: number
  sumber: string
  status: Prospect["status"]
  consent_status: Prospect["consent_status"]
  website: string | null
}

export type LeadDetail = Prospect & {
  rincian_confidence: { faktor: string; ada: boolean }[]
  bukti: { id: number; source_type: string; label: string; source_reference: string; dikumpulkan_pada: string | null }[]
  riwayat_skor: { skor: number; confidence: number | null; skor_versi: string; pemicu: string; dibuat_pada: string | null }[]
  aktivitas: { id: number; tipe: string; label: string; ringkasan: string | null; aktor: string; pada: string | null }[]
  duplikat: { id: number; tingkat: "pasti" | "mungkin"; alasan: AlasanDuplikat[]; lead: LeadRingkas }[]
}

export type DuplikatTinjauan = { id: number; tingkat: "pasti" | "mungkin"; alasan: AlasanDuplikat[]; lead: LeadRingkas; cocok: LeadRingkas; dibuat_pada: string | null }

export type TinjauanLead = {
  duplikat: DuplikatTinjauan[]
  perlu_tinjauan: (LeadRingkas & { alasan: string[]; confidence: number | null })[]
  jumlah_duplikat: number
  jumlah_perlu_tinjauan: number
}

export type LeadImporSumber = { sumber: Record<string, string>; kolom: string[]; kolom_wajib: string[]; maks_baris: number }

export type LeadImporPratinjau = {
  token: string
  nama_file: string
  status: string
  source_type: string
  source_reference: string
  dibuat_pada: string | null
  diterapkan_pada: string | null
  hasil: { baru: number; digabung: number; perlu_tinjauan: number; kembar_file: number; dilewati_salah: number } | null
  laporan: {
    ringkasan: { baris: number; valid: number; error: number; baru: number; digabung: number; perlu_tinjauan: number; kembar_file: number }
    error: (KesalahanLead & { baris: number })[]
    peringatan: string[]
    digabung: { baris: number; nama: string; wilayah: string; cocok_dengan: string; alasan: string[] }[]
    perlu_tinjauan: { baris: number; nama: string; wilayah: string; cocok_dengan: string[]; alasan: string[] }[]
    kembar_file: { baris: number; nama: string; wilayah: string; sama_dengan_baris: number }[]
    contoh: { baris: number; nama: string; wilayah: string; tipe: string; alamat: string; ada_telepon: boolean }[]
  }
}

export type LeadKonfigurasi = {
  segmen: string[]
  bobot: { geo_maks: number; telepon: number; jam: number; jalan: number; penalti_jaringan: number }
  ambang_confidence: number
  versi: string
  sementara: boolean
}

export type MarketArticle = { judul: string; tautan: string; cuplikan: string; sumber: string; tanggal: string }

export type MarketAnalysis = {
  status: "ok" | "tidak_terhubung" | "gagal"
  sumber: string
  periode: string
  wilayah: string
  dipindai: string
  ringkasan: string
  topik_utama: string | null
  topik: { id: string; label: string; kueri: string; jumlah_artikel: number; artikel: MarketArticle[] }[]
}

export type NextBestAction = {
  prioritas: "TINGGI" | "SEDANG" | "RENDAH"
  langkah: string
  topik: string
  teks: string
  produk: { sku: string; nama: string; izin_edar: string; klaim_resmi: string }[]
  penawaran: { bundling_box: number; diskon_persen: number; ongkir: string }
  kanal: string
  dasar: string[]
  verdict: Verdict
  aturan: string[]
  dirumuskan: string
  metode: string
}

// ------------------------------------------------------------------ ClaimGuard & Compliance Check

export type AuditStatus = "BLOCKED" | "NEED_REVIEW" | "ALLOWED" | "ERROR"

export type RegulatoryReference = {
  ref_id: string
  regulation_id: string
  regulation_title: string
  singkat: string
  article_reference: string
  ringkasan: string
  official_source_url: string
  official_pdf_url: string | null
  verification_status: "VERIFIED" | "UNVERIFIED"
  last_verified_at: string
  berlaku_untuk_produk?: boolean
}

export type ComplianceRuleMatch = {
  rule_id: string
  description: string
  severity: "blocked" | "review"
  confidence: string
  status_aturan: string
  match: string
  sentence: string
  start: number | null
  end: number | null
  decisive: boolean
  references: RegulatoryReference[]
}

export type ComplianceEvidence = {
  kutipan: string
  start: number | null
  end: number | null
  sumber: "aturan" | "pencocokan_klaim" | "llm"
  rule_id: string | null
  alasan: string
}

export type ComplianceAudit = {
  audit_id: string
  product_id: string
  draft_id: number | null
  draft_versi: number | null
  status: AuditStatus
  stage: "aturan" | "llm"
  reason: string
  violation_law: string | null
  regulatory_note: string | null
  matched_rules: ComplianceRuleMatch[]
  evidence: ComplianceEvidence[]
  references: RegulatoryReference[]
  recommendation: string | null
  recommendation_note: string | null
  rules_version: string
  engine_version: string
  model_provider: string | null
  model_name: string | null
  model_info: { provider: string; model: string; latency_ms: number | null; input_tokens: number; output_tokens: number } | null
  error_code: string | null
  input_text_hash: string
  text_length: number
  status_draf_diperbarui: boolean
  duration_ms: number
  actor_id: number | null
  created_at: string | null
}

export type DraftStatus =
  | "draf"
  | "diblokir"
  | "perlu_review"
  | "lolos_pemeriksaan"
  | "audit_gagal"
  | "menunggu_audit_ulang"
  | "disetujui"
  | "dibuang"

export type MarketingDraft = {
  id: number
  product_id: string | null
  product_name: string | null
  teks: string
  status: DraftStatus
  versi: number
  catatan_keputusan: string | null
  keputusan_oleh: number | null
  keputusan_pada: string | null
  dibuat_pada: string
  diperbarui_pada: string
}

export type LatestAuditResponse = { state: "ada" | "kosong"; audit: ComplianceAudit | null; draft: MarketingDraft | null }

export type ComplianceRegistry = {
  rules_version: string
  regulations: {
    id: string
    regulation_title: string
    singkat: string
    official_source_url: string
    status_berlaku: string
    verification_status: string
    last_verified_at: string
    catatan_ruang_lingkup: string
  }[]
  llm: { provider: string; model: string; dikonfigurasi: boolean; status_bila_gagal: AuditStatus }
  batas_teks: number
}

export type Kpi = {
  permintaan_tak_terpenuhi: { total: number; teratas: { istilah: string; jumlah: number; terakhir: string | null }[] }
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
  mode_data?: "produksi" | "demo"
  llm: { aktif: boolean; model: string; judge: string | null }
  whatsapp: { aktif: boolean; kanal_cadangan: string }
  kanal: Record<Channel, { label: string; aktif: boolean; jendela_balas_jam: number | null }>
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
  spesifikasi: "Isi & kandungan",
  minta_dokumen: "Minta katalog",
  perlu_staf: "Di luar wewenang AI",
  lainnya: "Lainnya",
}

export type KatalogMasalah = { baris: number; kolom: string; alasan: string; sheet?: string }

export type KatalogPratinjau = {
  token: string
  nama_file: string
  status: "pratinjau" | "diterapkan" | "dibatalkan"
  dibuat_pada: string
  laporan: {
    ringkasan: {
      baris: number
      valid: number
      error: number
      baru: number
      diubah: number
      tetap: number
      dinonaktifkan: number
      kebijakan: number | null
      kebijakan_error: number
      status_verifikasi?: Partial<Record<StatusVerifikasi, number>>
    }
    error: KatalogMasalah[]
    peringatan: KatalogMasalah[]
    jumlah_peringatan: number
    baru: string[]
    diubah: { nama: string; perubahan: string[] }[]
    dinonaktifkan: string[]
    contoh: { baris: number; sku: string; nama: string; harga_dasar: number; moq: number; stok: number | null; no_izin_edar: string; halal: string | null; bko: string | null }[]
    ganti_kebijakan: boolean
  }
}
