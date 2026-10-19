import type { Metadata, Viewport } from "next"
import { Fraunces, JetBrains_Mono, Plus_Jakarta_Sans } from "next/font/google"

import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"

import "./globals.css"

const jakarta = Plus_Jakarta_Sans({ variable: "--font-jakarta", subsets: ["latin"], weight: ["400", "500", "600", "700"] })
const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"], style: ["normal", "italic"], weight: ["400", "500"] })
const jetbrains = JetBrains_Mono({ variable: "--font-jetbrains", subsets: ["latin"], weight: ["400", "500"] })

export const metadata: Metadata = {
  title: { default: "AAGE · Arba'in Autonomous Growth Engine", template: "%s · AAGE" },
  description: "Agen penjualan & pemasaran AI CV Arba'in dengan ClaimGuard dan Evidence-to-Action Ledger.",
}

export const viewport: Viewport = { themeColor: "#06251C" }

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="id" className={`${jakarta.variable} ${fraunces.variable} ${jetbrains.variable}`}>
      <body className="antialiased">
        <TooltipProvider>{children}</TooltipProvider>
        <Toaster position="bottom-right" theme="light" richColors closeButton />
      </body>
    </html>
  )
}
