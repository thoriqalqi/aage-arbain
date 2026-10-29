import type { Metadata, Viewport } from "next"
import { Fraunces, Inter, JetBrains_Mono } from "next/font/google"

import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"

import "./globals.css"

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] })
const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"], weight: ["400", "500", "600"] })
const jetbrains = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"], weight: ["400", "500"] })

export const metadata: Metadata = {
  title: { default: "AAGE · Arba'in Autonomous Growth Engine", template: "%s · AAGE" },
  description: "Agen penjualan & pemasaran AI CV Arba'in dengan ClaimGuard dan Evidence-to-Action Ledger.",
}

export const viewport: Viewport = { themeColor: "#0F3D2E" }

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="id" className={`${inter.variable} ${fraunces.variable} ${jetbrains.variable}`}>
      <body className="antialiased">
        <TooltipProvider>{children}</TooltipProvider>
        <Toaster position="bottom-right" theme="light" richColors closeButton />
      </body>
    </html>
  )
}
