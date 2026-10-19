# design.md — AAGE (Arba'in Autonomous Growth Engine)

Panduan desain UI untuk MVP AAGE. Dokumen ini menjadi acuan bagi frontend (Next.js + Tailwind + shadcn/ui) dan bagi siapa pun (termasuk AI coding agent) yang membangun halaman baru. Lihat `PRD` untuk fungsi tiap modul; dokumen ini hanya mengatur **tampilan, rasa, dan gerak**.

---

## 1. Arah desain

**Satu kalimat:** *"Ruang kerja yang tenang dan terpercaya: cream yang lembut, kaca cair yang ringan, dan emerald gelap yang elegan sebagai jangkar."*

Prinsip:

1. **Tenang dulu, baru indah.** Staf UMKM harus paham layar dalam 5 detik. Efek visual (glass, gradient, 3D) tidak boleh mengalahkan data.
2. **Kepercayaan terlihat.** Setiap jawaban AI menampilkan sumber, verdict ClaimGuard, dan biaya. Desain membuat "bukti" mudah dilihat, bukan disembunyikan.
3. **Terang di area kerja, gelap di jangkar.** Konten di atas cream terang; navigasi, hero, dan momen penting memakai *elegant dark emerald*.
4. **Gerak yang bermakna.** Animasi menjelaskan perubahan status (dikirim, ditahan, diblokir), bukan dekorasi.
5. **Satu aksi utama per layar.** Tombol primer emerald hanya satu di setiap area.

Kata kunci rasa: *clean, profesional, soft, liquid glass, elegant dark, emerald, calm motion*.

---

## 2. Warna

### 2.1 Palet dasar

| Token | Hex | Pemakaian |
|---|---|---|
| `cream-50` | `#FCFBF7` | Background utama (cream agak putih) |
| `cream-100` | `#F7F4EC` | Background sekunder, area tabel bergaris |
| `cream-200` | `#EEE9DC` | Border lembut, divider |
| `ink-900` | `#0E1A16` | Teks utama (hitam kehijauan, bukan hitam murni) |
| `ink-600` | `#4A5A54` | Teks sekunder |
| `ink-400` | `#8A968F` | Placeholder, teks nonaktif |
| `emerald-950` | `#06251C` | Elegant dark: sidebar, hero, panel gelap |
| `emerald-900` | `#0B3D2E` | Primary (tombol, link aktif) |
| `emerald-700` | `#0F5C45` | Primary hover |
| `emerald-500` | `#16A37A` | Aksen, fokus, grafik seri utama |
| `emerald-100` | `#D7F2E6` | Latar badge/aksen lembut |
| `mint-glow` | `#A7F3D0` | Highlight gradient, glow tipis |
| `champagne-300` | `#E6D3A8` | Aksen elegan sangat hemat (garis tipis, ikon premium, gradient) |

Aturan: **emerald-900 = aksi**, **emerald-950 = jangkar gelap**, **champagne = bumbu** (maksimal 5% layar).

### 2.2 Warna status (ClaimGuard & sistem)

Status tidak boleh dibedakan hanya lewat warna; selalu dengan ikon + label.

| Status | Teks/ikon | Latar | Ikon (lucide) | Label |
|---|---|---|---|---|
| Diizinkan | `#13795B` | `#E3F5EC` | `ShieldCheck` | Diizinkan |
| Perlu review | `#A15C07` | `#FBF0DC` | `ShieldAlert` | Perlu review |
| Diblokir | `#B42318` | `#FDE7E4` | `ShieldX` | Diblokir |
| Info/AI | `#1F5F8B` | `#E4EFF7` | `Sparkles` | Dijawab AI |
| Eskalasi | `#6B4FA0` | `#EEE8F7` | `UserRoundCheck` | Menunggu staf |

### 2.3 Palet grafik

Urutan seri: `#16A37A` (emerald), `#0B3D2E` (emerald gelap), `#C9A86A` (champagne tua), `#5B8DB8` (biru kabut), `#B9C4BE` (abu hijau). Grid `#EEE9DC`, sumbu `#8A968F`. Maksimal 4 seri per grafik.

### 2.4 Gradient lembut

Background aplikasi = cream + dua "blob" gradient yang sangat pudar dan bergerak pelan:

```css
.app-bg {
  background:
    radial-gradient(60rem 40rem at 10% -10%, rgb(167 243 208 / 0.35), transparent 60%),
    radial-gradient(50rem 36rem at 110% 10%, rgb(230 211 168 / 0.30), transparent 60%),
    radial-gradient(40rem 30rem at 50% 120%, rgb(22 163 122 / 0.10), transparent 60%),
    #FCFBF7;
}
```

Gradient gelap (sidebar/hero):

```css
.dark-anchor {
  background:
    radial-gradient(30rem 20rem at 0% 0%, rgb(22 163 122 / 0.25), transparent 60%),
    radial-gradient(24rem 18rem at 100% 100%, rgb(230 211 168 / 0.10), transparent 60%),
    linear-gradient(180deg, #082E22 0%, #06251C 100%);
}
```

---

## 3. Liquid glass

Glass dipakai untuk **permukaan yang melayang**: topbar, kartu KPI, panel detail, dialog, chat composer. Tabel data padat **tidak** memakai glass penuh (pakai `surface` putih solid agar teks tajam).

### 3.1 Resep

```css
/* Kaca terang (default) */
.glass {
  background: linear-gradient(135deg, rgb(255 255 255 / 0.72), rgb(255 255 255 / 0.48));
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border: 1px solid rgb(255 255 255 / 0.70);
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 0.85),        /* kilau tepi atas */
    inset 0 -1px 0 rgb(14 26 22 / 0.04),
    0 1px 2px rgb(14 26 22 / 0.04),
    0 12px 32px -8px rgb(11 61 46 / 0.12);       /* bayangan emerald lembut */
  border-radius: var(--radius-xl);
}

/* Kaca gelap (elegant dark) */
.glass-dark {
  background: linear-gradient(135deg, rgb(11 61 46 / 0.78), rgb(6 37 28 / 0.86));
  backdrop-filter: blur(24px) saturate(140%);
  border: 1px solid rgb(255 255 255 / 0.08);
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 0.10),
    0 20px 48px -12px rgb(6 37 28 / 0.45);
  color: #F3F1EA;
}

/* Kilau "liquid": highlight bergerak di tepi saat hover */
.glass-sheen { position: relative; overflow: hidden; }
.glass-sheen::after {
  content: ""; position: absolute; inset: -40%;
  background: conic-gradient(from 180deg, transparent 0 70%, rgb(255 255 255 / 0.35) 80%, transparent 90%);
  opacity: 0; transition: opacity .4s var(--ease-out);
  pointer-events: none;
}
.glass-sheen:hover::after { opacity: 1; animation: sheen 2.4s linear infinite; }
@keyframes sheen { to { transform: rotate(1turn); } }
```

### 3.2 Aturan glass

- Teks di atas glass minimal kontras **4.5:1**. Jika latar di belakang ramai, naikkan opasitas glass ke 0.8.
- Maksimal **2 lapis** glass bertumpuk.
- Fallback tanpa `backdrop-filter` (browser lama/hemat daya): `background: rgb(255 255 255 / 0.92)`.
- Saat `prefers-reduced-transparency: reduce`, gunakan permukaan solid.

---

## 4. Tipografi

| Peran | Font | Ukuran / line-height | Berat |
|---|---|---|---|
| Display (hero, login) | **Fraunces** (serif elegan, opsional italic) | 40/48, 32/40 | 500 |
| Heading halaman | **Plus Jakarta Sans** | 24/32 | 650 |
| Heading kartu | Plus Jakarta Sans | 16/24 | 600 |
| Body | Plus Jakarta Sans | 14/22 | 400–500 |
| Caption, label tabel | Plus Jakarta Sans | 12/16, letter-spacing 0.02em | 500 |
| Angka KPI | Plus Jakarta Sans, `tabular-nums` | 32/40 | 650 |
| ID, hash, JSON | **JetBrains Mono** | 12/18 | 400 |

Plus Jakarta Sans adalah typeface buatan desainer Indonesia, cocok dengan narasi komponen lokal. Muat lewat `next/font/google`.

Bahasa antarmuka: **Bahasa Indonesia**, kalimat pendek, sopan, tanpa jargon teknis untuk staf (misalnya "Menunggu persetujuan", bukan "Pending approval").

---

## 5. Spasi, radius, bayangan

- **Grid spasi 4px**: 4, 8, 12, 16, 20, 24, 32, 40, 56, 72.
- **Radius**: `sm 8px` (input, badge), `md 12px` (tombol), `lg 16px` (kartu), `xl 24px` (panel glass, dialog), `full` (chip, avatar).
- **Bayangan** (selalu bernuansa emerald, bukan hitam):
  - `shadow-xs`: `0 1px 2px rgb(14 26 22 / .05)`
  - `shadow-md`: `0 8px 24px -6px rgb(11 61 46 / .10)`
  - `shadow-lg`: `0 20px 48px -12px rgb(11 61 46 / .18)`
  - `shadow-glow`: `0 0 0 4px rgb(22 163 122 / .15)` (fokus/terpilih)
- **Lebar konten**: maks 1440px; padding halaman 24px (desktop), 16px (mobile).

---

## 6. Token untuk shadcn/ui (Tailwind v4)

Tempel di `app/globals.css`. Variabel mengikuti konvensi shadcn agar semua komponen langsung ikut tema.

```css
@import "tailwindcss";

:root {
  --radius: 0.75rem;

  --background: #FCFBF7;
  --foreground: #0E1A16;
  --card: #FFFFFF;
  --card-foreground: #0E1A16;
  --popover: #FFFFFF;
  --popover-foreground: #0E1A16;

  --primary: #0B3D2E;
  --primary-foreground: #F3F1EA;
  --secondary: #F7F4EC;
  --secondary-foreground: #0E1A16;
  --muted: #F7F4EC;
  --muted-foreground: #4A5A54;
  --accent: #D7F2E6;
  --accent-foreground: #0B3D2E;
  --destructive: #B42318;

  --border: #EEE9DC;
  --input: #E4DED0;
  --ring: #16A37A;

  --chart-1: #16A37A;
  --chart-2: #0B3D2E;
  --chart-3: #C9A86A;
  --chart-4: #5B8DB8;
  --chart-5: #B9C4BE;

  --sidebar: #06251C;
  --sidebar-foreground: #E8E4D8;
  --sidebar-primary: #A7F3D0;
  --sidebar-primary-foreground: #06251C;
  --sidebar-accent: rgb(255 255 255 / 0.06);
  --sidebar-accent-foreground: #FFFFFF;
  --sidebar-border: rgb(255 255 255 / 0.08);
  --sidebar-ring: #16A37A;

  /* status */
  --ok: #13795B;      --ok-bg: #E3F5EC;
  --review: #A15C07;  --review-bg: #FBF0DC;
  --blocked: #B42318; --blocked-bg: #FDE7E4;

  /* motion */
  --ease-out: cubic-bezier(0.22, 1, 0.36, 1);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
  --dur-fast: 150ms;
  --dur-base: 240ms;
  --dur-slow: 420ms;
}

@theme inline {
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);
  --color-chart-4: var(--chart-4);
  --color-chart-5: var(--chart-5);
  --color-sidebar: var(--sidebar);
  --color-sidebar-foreground: var(--sidebar-foreground);
  --color-sidebar-primary: var(--sidebar-primary);
  --color-sidebar-primary-foreground: var(--sidebar-primary-foreground);
  --color-sidebar-accent: var(--sidebar-accent);
  --color-sidebar-accent-foreground: var(--sidebar-accent-foreground);
  --color-sidebar-border: var(--sidebar-border);
  --color-sidebar-ring: var(--sidebar-ring);
  --color-ok: var(--ok);         --color-ok-bg: var(--ok-bg);
  --color-review: var(--review); --color-review-bg: var(--review-bg);
  --color-blocked: var(--blocked); --color-blocked-bg: var(--blocked-bg);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: var(--radius);
  --radius-lg: calc(var(--radius) + 4px);
  --radius-xl: calc(var(--radius) + 12px);
  --font-sans: var(--font-jakarta);
  --font-display: var(--font-fraunces);
  --font-mono: var(--font-jetbrains);
}

body { @apply bg-background text-foreground antialiased; }
```

Tema gelap penuh **tidak** termasuk MVP. Nuansa "dark" hadir lewat sidebar, hero, dan panel `glass-dark`.

---

## 7. Komponen

### 7.1 shadcn/ui yang dipakai

`button`, `card`, `badge`, `table` (+ TanStack Table untuk data table), `tabs`, `dialog`, `sheet`, `dropdown-menu`, `command` (palet ⌘K), `tooltip`, `sonner` (toast), `skeleton`, `chart` (Recharts), `form` + `input` + `textarea` + `select`, `scroll-area`, `separator`, `avatar`, `progress`, `resizable`, `sidebar`, `breadcrumb`, `hover-card`, `toggle-group`.

Ikon: **lucide-react**, stroke 1.75, ukuran 16 (inline) / 20 (navigasi).

### 7.2 Varian kustom

| Komponen | Deskripsi |
|---|---|
| `GlassCard` | `Card` + kelas `.glass`; prop `tone="light" \| "dark"`, `sheen?: boolean` |
| `Button` varian | `default` (emerald-900, teks cream), `glass` (kaca terang), `ghost`, `outline` (border cream-200), `destructive`. Tinggi 36 (default), 32 (sm), 44 (lg). Hover: naik 1px + shadow-md |
| `VerdictBadge` | Badge status ClaimGuard dengan ikon + label; tooltip menampilkan aturan yang terpicu |
| `ClaimHighlight` | Teks dengan `<mark>` per kalimat: hijau/kuning/merah lembut, garis bawah bergelombang untuk "Diblokir"; klik → popover alasan + saran kalimat aman |
| `SourceChip` | Chip kecil "📄 Katalog v3 · hal 2" (pakai ikon `FileText`), klik membuka sumber di `Sheet` |
| `CostChip` | Biaya AI per item, mono, contoh `Rp 38` |
| `ChatBubble` | Bubble gaya WhatsApp yang diperhalus: pembeli = putih, AI = emerald-100, staf = champagne tipis; footer berisi `VerdictBadge` + `SourceChip` |
| `ApprovalCard` | Ringkasan chat, alasan eskalasi, draf balasan editable, tiga aksi: **Setujui & kirim** (primer), Edit, Tolak |
| `LedgerTimeline` | Timeline vertikal event; tiap event = ikon tipe, waktu, aktor (AI/staf), verdict, biaya; garis penghubung emerald tipis |
| `KpiTile` | GlassCard dengan angka besar `tabular-nums`, delta, sparkline 7 hari |
| `ScoreBar` | Bar 0–100 dengan gradient emerald, angka di kanan, tooltip alasan skor |
| `FunnelChart` | Funnel lead: prospek → dihubungi → merespons → minta penawaran → draf pesanan |
| `EmptyState` | Ilustrasi orb glass kecil + kalimat + satu aksi |

---

## 8. Layout aplikasi

### 8.1 App shell

```
┌──────────────┬───────────────────────────────────────────────────────┐
│  SIDEBAR     │  TOPBAR (glass, sticky)                               │
│  elegant     │  Breadcrumb · ⌘K cari · status WA ● · avatar          │
│  dark        ├───────────────────────────────────────────────────────┤
│  emerald     │                                                       │
│  248px       │   KONTEN di atas cream + soft gradient                │
│  (collapse   │   (kartu glass / tabel putih solid)                    │
│   72px)      │                                                       │
│              │                                                       │
│  ● Ringkasan │                                                       │
│  ● Inbox  (3)│                                                       │
│  ● Approval  │                                                       │
│  ● Ledger    │                                                       │
│  ● Konten    │                                                       │
│  ● Prospek   │                                                       │
│  ● ClaimGuard│                                                       │
│  ● Katalog   │                                                       │
│  ──────────  │                                                       │
│  Biaya AI    │                                                       │
│  bulan ini   │                                                       │
│  Rp 41.200   │                                                       │
└──────────────┴───────────────────────────────────────────────────────┘
```

- Sidebar memakai `.dark-anchor`; item aktif = pill `mint-glow` 12% + garis kiri 2px mint.
- Badge jumlah di "Inbox" dan "Approval" berdenyut pelan sekali saat bertambah.
- Kartu mini "Biaya AI bulan ini" di bawah sidebar menegaskan efisiensi biaya.

### 8.2 Halaman

**Ringkasan (KPI)**
Baris 4 `KpiTile`: Chat hari ini, % dijawab otomatis, Klaim diblokir/ditahan, Biaya per percakapan. Di bawahnya: `FunnelChart` (kiri, 2/3) + "Butuh tindakan" (kanan, 1/3, daftar approval teratas). Baris terakhir: grafik volume chat 14 hari.

**Inbox**
Tiga kolom `resizable`: daftar percakapan (filter status) | chat (bubble + composer glass) | panel konteks (profil toko, pesanan terakhir, `LedgerTimeline` percakapan). Status chat ditandai titik warna + label.

**Approval**
Antrean kartu `ApprovalCard`, diurutkan dari yang paling lama menunggu. Pintasan keyboard: `A` setujui, `E` edit, `R` tolak, `J/K` pindah. Setelah disetujui, kartu meluncur keluar dan toast "Terkirim ke WhatsApp".

**Ledger**
Data table (filter: tanggal, tipe event, verdict, aktor). Klik baris → `Sheet` kanan berisi rantai event lengkap sampai dokumen sumber. Kolom ID memakai font mono.

**ClaimGuard Playground**
Dua panel: kiri textarea/URL, kanan hasil `ClaimHighlight` + ringkasan (jumlah diizinkan/review/diblokir). Tombol "Salin versi aman".

**Konten & GEO Studio**
Wizard 3 langkah dalam satu halaman: pilih produk & topik → pratinjau draf (tab: Artikel, FAQ, JSON-LD, Meta) → verdict ClaimGuard + Setujui/Ekspor. Mode "Audit halaman": masukkan URL → kartu sebelum/sesudah berdampingan.

**Prospek**
Header filter (wilayah, jenis toko) + tombol "Petakan". Tampilan dua mode (`toggle-group`): **Tabel** (skor, nama, jarak, rating, status) dan **Peta** (opsional, Leaflet + tile terang). Klik prospek → `Sheet` berisi alasan skor + draf pesan pembuka.

**Katalog (Knowledge Base)**
Tabel produk + tab Dokumen + tab Klaim disetujui + tab Tier harga. Unggah via dropzone glass.

**Login**
Layar terbelah: kiri hero `dark-anchor` dengan objek 3D (lihat bagian 10) dan headline Fraunces "Penjualan yang tumbuh, klaim yang tetap jujur."; kanan form login di atas cream.

**Web chat cadangan (mobile 375px)**
Tampilan seperti WhatsApp yang diperhalus, header emerald-950, bubble sesuai `ChatBubble`. Dipakai saat demo bila WhatsApp bermasalah.

---

## 9. Motion

Library: **Motion** (`motion/react`, penerus Framer Motion). CSS transition untuk hover sederhana.

| Momen | Animasi | Durasi / easing |
|---|---|---|
| Masuk halaman | Fade + naik 8px, anak bertahap (stagger 40ms) | 240ms, `ease-out` |
| Hover kartu | Naik 2px, shadow-md → shadow-lg, sheen glass | 150ms |
| Pesan AI muncul | Indikator mengetik 3 titik → teks muncul per kata (streaming) | ±20ms per kata |
| Verdict ClaimGuard | Badge "memindai" (shimmer) → berubah ke verdict dengan pop skala 0.96→1 | 420ms |
| Klaim diblokir | Garis bawah merah tergambar dari kiri ke kanan + shake halus 2px sekali | 420ms |
| Approval disetujui | Kartu bergeser keluar ke kanan + kolaps tinggi; toast muncul | 320ms |
| Angka KPI | Count-up dari nilai sebelumnya | 600ms |
| Ledger event baru | Titik timeline berdenyut sekali (ring emerald) | 600ms |
| Background blob | Gradient blob bergeser sangat pelan | 30–40 detik, loop |
| Skeleton | Shimmer cream → putih | 1.2 detik loop |

Aturan:
- Tidak ada animasi > 600ms pada interaksi.
- Hanya animasikan `transform` dan `opacity`.
- `prefers-reduced-motion: reduce` → matikan blob, sheen, shake, dan 3D; transisi jadi fade 100ms.

---

## 10. Three.js (opsional, hemat)

Tujuan: memberi kesan *deeptech* dan *liquid glass* di momen pertama, **bukan** di halaman kerja.

- **Di mana:** hero Login, slide/landing demo, dan empty state besar. Tidak dipakai di Inbox, Approval, Ledger, atau tabel.
- **Apa:** satu orb kaca cair berwarna emerald yang mengambang dan berubah bentuk pelan (noise displacement), dengan beberapa partikel kecil seperti "data" yang mengorbit, dan pantulan cahaya champagne.
- **Stack:** `@react-three/fiber` + `@react-three/drei` (`MeshTransmissionMaterial`, `Float`, `Environment preset="city"`).
- **Parameter awal:** transmission 1, thickness 0.6, roughness 0.15, chromaticAberration 0.03, warna `#16A37A`, distortion 0.3, kecepatan noise 0.2.
- **Performa:** di-lazy-load (`next/dynamic`, `ssr:false`), `dpr={[1, 1.5]}`, berhenti render saat tab tidak terlihat (`frameloop="demand"` + `IntersectionObserver`), anggaran < 3 ms/frame. Fallback gambar statis (PNG/WebP orb) untuk perangkat lemah, tanpa WebGL, atau reduced motion.
- **Interaksi:** orb sedikit mengikuti posisi kursor (parallax ±6°), tanpa klik.

---

## 11. Data visualisasi

- Pakai `chart` dari shadcn (Recharts) dengan token `--chart-*`.
- Garis 2px, titik hanya saat hover, area fill gradient emerald 20% → 0%.
- Grid horizontal saja, warna `cream-200`. Tanpa border kotak grafik.
- Angka sumbu `tabular-nums`, format Indonesia (`Rp 1.250`, `12,5%`, `19 Okt`).
- Tooltip = glass kecil dengan nilai tebal + label tanggal.
- Funnel: bar horizontal yang lebarnya proporsional, persentase konversi antar tahap ditulis di antara bar.

---

## 12. Aksesibilitas & kegunaan

- Kontras teks ≥ 4.5:1; teks besar ≥ 3:1. Cek ulang setiap teks di atas glass.
- Fokus keyboard: ring 2px `#16A37A` + offset 2px, selalu terlihat.
- Semua status punya ikon + label; jangan mengandalkan warna.
- Target sentuh minimal 40×40px (web chat mobile 44×44px).
- Toast tidak menjadi satu-satunya bukti aksi; status di daftar ikut berubah.
- Format lokal: tanggal `19 Okt 2026, 20.33`, mata uang `Rp`, desimal koma.

---

## 13. Responsif

| Breakpoint | Perilaku |
|---|---|
| ≥1280px | Layout penuh, Inbox 3 kolom |
| 1024–1279px | Sidebar collapse otomatis ke ikon (72px), panel konteks Inbox jadi `Sheet` |
| 768–1023px | Inbox 1 kolom dengan navigasi bertahap; tabel bisa di-scroll horizontal dengan kolom pertama sticky |
| <768px | Hanya web chat dan Approval yang dioptimalkan; halaman lain tampil dasar |

---

## 14. Struktur file frontend (saran)

```
apps/web/
  app/
    (auth)/login/page.tsx
    (app)/layout.tsx            # sidebar + topbar
    (app)/page.tsx              # Ringkasan
    (app)/inbox/…  approval/…  ledger/…  konten/…  prospek/…  claimguard/…  katalog/…
    chat/page.tsx               # web chat cadangan
    globals.css                 # token bagian 6
  components/
    ui/                         # shadcn (jangan diubah langsung, bungkus di aage/)
    aage/                       # GlassCard, VerdictBadge, ClaimHighlight, LedgerTimeline, …
    three/LiquidOrb.tsx
  lib/format.ts                 # Rp, tanggal, persen (id-ID)
```

---

## 15. Checklist sebelum demo

- [ ] Semua halaman memakai token, tidak ada hex lepas di komponen
- [ ] Satu tombol primer per area
- [ ] Verdict ClaimGuard tampil dengan ikon + label di chat, approval, konten, dan ledger
- [ ] Glass terbaca jelas di proyektor (uji di layar terang dan redup)
- [ ] Reduced motion dan fallback 3D berfungsi
- [ ] Angka dan tanggal berformat Indonesia
- [ ] Waktu muat halaman ≤ 2 detik; orb 3D tidak membuat laptop demo panas
