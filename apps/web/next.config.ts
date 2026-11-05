import type { NextConfig } from "next"

const API_URL = process.env.API_URL || "http://localhost:8000"

const nextConfig: NextConfig = {
  output: "standalone",
  // Folder build terpisah agar dua dev server (mis. port 3000 & 3010) bisa jalan bersamaan.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  experimental: {
    // Bawaan 30 detik memotong audit Compliance, yang boleh memakai LLM sampai CLAIMGUARD_LLM_TIMEOUT_S (60 detik).
    proxyTimeout: 90_000,
  },
  async rewrites() {
    // Dashboard & web chat memanggil /api/* di origin yang sama → diteruskan ke FastAPI.
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }]
  },
  async redirects() {
    // Rute lama → struktur 11 layar Brief §5.
    return [
      { source: "/prospek", destination: "/leads", permanent: false },
      { source: "/claimguard", destination: "/compliance", permanent: false },
      { source: "/ledger", destination: "/compliance?tab=ledger", permanent: false },
      { source: "/katalog", destination: "/pengaturan?tab=katalog", permanent: false },
    ]
  },
}

export default nextConfig
