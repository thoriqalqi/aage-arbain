import type { NextConfig } from "next"

const API_URL = process.env.API_URL || "http://localhost:8000"

const nextConfig: NextConfig = {
  output: "standalone",
  // Folder build terpisah agar dua dev server (mis. port 3000 & 3010) bisa jalan bersamaan.
  distDir: process.env.NEXT_DIST_DIR || ".next",
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
