import type { NextConfig } from "next"

const API_URL = process.env.API_URL || "http://localhost:8000"

const nextConfig: NextConfig = {
  output: "standalone",
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
