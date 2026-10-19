/** Fallback statis orb (tanpa WebGL / reduced motion / saat memuat). */
export function StaticOrb({ className = "" }: { className?: string }) {
  return (
    <div className={`relative aspect-square ${className}`} aria-hidden>
      <div className="absolute inset-[12%] rounded-full bg-[radial-gradient(circle_at_32%_28%,rgb(255_255_255/0.9),transparent_22%),radial-gradient(circle_at_50%_50%,var(--mint-glow),var(--emerald-500)_50%,var(--emerald-900)_85%)] opacity-90 shadow-[0_0_120px_-10px_rgb(22_163_122/0.6)]" />
      <div className="absolute inset-[12%] rounded-full bg-[radial-gradient(circle_at_70%_80%,rgb(230_211_168/0.45),transparent_40%)]" />
    </div>
  )
}
