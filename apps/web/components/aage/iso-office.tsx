"use client"

import { cn } from "@/lib/utils"

export type DeskState = "bekerja" | "menunggu" | "idle" | "jeda"

export type Desk = { id: string; label: string; state: DeskState }

// Proyeksi isometrik sederhana: satu unit grid = 64×32 px.
const OX = 300
const OY = 56
const iso = (gx: number, gy: number, lift = 0): [number, number] => [OX + (gx - gy) * 64, OY + (gx + gy) * 32 - lift]
const pts = (...p: [number, number][]) => p.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")

const SCREEN: Record<DeskState, string> = {
  bekerja: "var(--brand-400)",
  menunggu: "var(--gold-500)",
  idle: "var(--forest-700)",
  jeda: "var(--subtle-foreground)",
}

// Posisi 6 meja (3 kolom × 2 baris) di lantai 6×4.
const SLOTS: [number, number][] = [
  [1, 1],
  [3, 1],
  [5, 1],
  [1, 3],
  [3, 3],
  [5, 3],
]

function DeskShape({ desk, cx, cy, selected, onSelect }: { desk: Desk; cx: number; cy: number; selected: boolean; onSelect: () => void }) {
  const x0 = cx - 0.62
  const x1 = cx + 0.62
  const y0 = cy - 0.36
  const y1 = cy + 0.36
  const h = 16
  const top = pts(iso(x0, y0, h), iso(x1, y0, h), iso(x1, y1, h), iso(x0, y1, h))
  const right = pts(iso(x1, y0, h), iso(x1, y1, h), iso(x1, y1), iso(x1, y0))
  const front = pts(iso(x0, y1, h), iso(x1, y1, h), iso(x1, y1), iso(x0, y1))

  // Monitor berdiri di sisi belakang meja.
  const m0 = iso(x0 + 0.32, y0 + 0.16, h)
  const m1 = iso(x1 - 0.32, y0 + 0.16, h)
  const mh = 30
  const monitor = pts(m0, m1, [m1[0], m1[1] - mh], [m0[0], m0[1] - mh])
  const screen = pts([m0[0] + 3, m0[1] - 4], [m1[0] - 3, m1[1] - 4], [m1[0] - 3, m1[1] - mh + 3], [m0[0] + 3, m0[1] - mh + 3])

  // Agen duduk di depan meja.
  const [ax, ay] = iso(cx + 0.1, cy + 0.78)
  const [lx, ly] = iso(cx, cy - 0.36, h + mh + 20)
  const working = desk.state === "bekerja"

  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={`${desk.label}, ${desk.state}`}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect())}
      className="cursor-pointer outline-none [&:focus-visible_.desk-top]:stroke-[var(--ring)]"
    >
      {/* bayangan */}
      <polygon points={pts(iso(x0 - 0.06, y0 + 0.1), iso(x1 + 0.1, y0 + 0.1), iso(x1 + 0.1, y1 + 0.16), iso(x0 - 0.06, y1 + 0.16))} fill="rgb(23 34 29 / 0.05)" />
      <polygon points={right} fill="#ddd5c2" />
      <polygon points={front} fill="#e7e0cf" />
      <polygon
        className="desk-top transition-colors"
        points={top}
        fill={selected ? "var(--brand-100)" : "#f3eee2"}
        stroke={selected ? "var(--brand-500)" : "#e2dac8"}
        strokeWidth={selected ? 1.5 : 1}
      />
      <polygon points={monitor} fill="var(--forest-900)" />
      <polygon points={screen} fill={SCREEN[desk.state]} opacity={desk.state === "jeda" ? 0.5 : 0.9} className={working ? "breathe" : undefined} />

      {/* agen */}
      <ellipse cx={ax} cy={ay + 2} rx={13} ry={6} fill="rgb(23 34 29 / 0.06)" />
      <path d={`M ${ax - 10} ${ay} q 0 -18 10 -18 q 10 0 10 18 z`} fill={desk.state === "jeda" ? "#c9cdc8" : "var(--forest-800)"} />
      <circle cx={ax} cy={ay - 24} r={7} fill="#e9c9a6" />

      {/* label */}
      <g transform={`translate(${lx}, ${ly})`}>
        <rect x={-34} y={-11} width={68} height={22} rx={11} fill="var(--card)" stroke={selected ? "var(--brand-500)" : "var(--line)"} />
        <circle cx={-22} cy={0} r={3} fill={SCREEN[desk.state]} />
        <text x={4} y={4} textAnchor="middle" fontSize={11} fontWeight={600} fill="var(--forest-900)" fontFamily="var(--font-inter)">
          {desk.label}
        </text>
      </g>
    </g>
  )
}

/** Ilustrasi kantor isometrik 6 meja (Brief §5 — layar Agen). */
export function IsoOffice({ desks, selected, onSelect, className }: { desks: Desk[]; selected: string; onSelect: (id: string) => void; className?: string }) {
  const floor = pts(iso(0, 0), iso(6, 0), iso(6, 4), iso(0, 4))
  const lines: [number, number, number, number][] = []
  for (let i = 1; i < 6; i++) lines.push([...iso(i, 0), ...iso(i, 4)])
  for (let j = 1; j < 4; j++) lines.push([...iso(0, j), ...iso(6, j)])
  const [wl0, wl1, wl2] = [iso(0, 4), iso(0, 0), iso(6, 0)]
  const wallH = 46

  return (
    <svg viewBox="40 0 660 420" className={cn("h-auto w-full select-none", className)} role="group" aria-label="Kantor virtual enam agen">
      {/* dinding belakang */}
      <polygon points={pts(wl0, wl1, [wl1[0], wl1[1] - wallH], [wl0[0], wl0[1] - wallH])} fill="#eeebe2" />
      <polygon points={pts(wl1, wl2, [wl2[0], wl2[1] - wallH], [wl1[0], wl1[1] - wallH])} fill="#e7e3d8" />
      {/* lantai */}
      <polygon points={floor} fill="var(--card)" stroke="var(--line)" />
      {lines.map(([x1, y1, x2, y2], i) => (
        <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--line)" strokeWidth={0.75} opacity={0.7} />
      ))}
      {/* tanaman di pojok */}
      {(() => {
        const [px, py] = iso(5.6, 0.35)
        return (
          <g>
            <path d={`M ${px - 7} ${py} l 2 -12 h 10 l 2 12 z`} fill="var(--gold-500)" />
            <circle cx={px - 4} cy={py - 18} r={7} fill="var(--brand-500)" />
            <circle cx={px + 5} cy={py - 20} r={6} fill="var(--brand-400)" />
            <circle cx={px} cy={py - 27} r={6} fill="var(--forest-700)" />
          </g>
        )
      })()}
      {/* urutkan dari belakang ke depan agar tumpukan benar */}
      {desks.slice(0, 6).map((d, i) => (
        <DeskShape key={d.id} desk={d} cx={SLOTS[i][0]} cy={SLOTS[i][1]} selected={selected === d.id} onSelect={() => onSelect(d.id)} />
      ))}
    </svg>
  )
}
