"use client"

// "Virtual AI Agent Office" — maket kantor isometrik 3D (React Three Fiber).
// Dimuat lewat next/dynamic (ssr:false) dari app/dashboard/page.tsx agar tidak memicu error hydration.

import { Grid, Html, Line, OrbitControls, OrthographicCamera, RoundedBox } from "@react-three/drei"
import { Canvas, useFrame } from "@react-three/fiber"
import { useMemo, useRef } from "react"
import * as THREE from "three"

export type AgentId = "b2b_sales_agent" | "lead_miner_agent" | "geo_content_agent" | "claim_guard_agent"

export const DESKS: { id: AgentId; label: string; pos: [number, number, number]; color: string }[] = [
  { id: "b2b_sales_agent", label: "Sales Agent", pos: [-3.4, 0, -3.4], color: "#10b981" },
  { id: "lead_miner_agent", label: "Lead Miner", pos: [3.4, 0, -3.4], color: "#34d399" },
  { id: "geo_content_agent", label: "GEO Marketer", pos: [-3.4, 0, 3.4], color: "#6ee7b7" },
  { id: "claim_guard_agent", label: "ClaimGuard Watchdog", pos: [3.4, 0, 3.4], color: "#f43f5e" },
]
const NEON = new THREE.Color("#10b981")
const SERVER_TOP: [number, number, number] = [0, 1.6, 0]

/** Waktu (performance.now) event terakhir per agen + apakah ClaimGuard sedang alert. */
export type Activity = Partial<Record<AgentId, number>>

function useActive(activity: Activity, id: AgentId, windowMs = 1800) {
  const ref = useRef(0)
  return (now: number) => {
    const last = activity[id] ?? -1e9
    const target = now - last < windowMs ? 1 : 0
    ref.current += (target - ref.current) * 0.12
    return ref.current
  }
}

function ServerCore({ busy }: { busy: number }) {
  const core = useRef<THREE.MeshStandardMaterial>(null)
  const ring = useRef<THREE.Mesh>(null)
  const light = useRef<THREE.PointLight>(null)
  useFrame(({ clock }) => {
    const t = clock.getElapsedTime()
    const pulse = 0.6 + 0.4 * Math.sin(t * 1.6) // pulse lambat
    if (core.current) core.current.emissiveIntensity = 1.2 + pulse * 1.5 + busy * 1.2
    if (light.current) light.current.intensity = 6 + pulse * 6 + busy * 8
    if (ring.current) ring.current.rotation.y = t * (0.4 + busy * 1.5)
  })
  return (
    <group>
      {/* alas */}
      <mesh position={[0, 0.1, 0]} receiveShadow>
        <cylinderGeometry args={[1.35, 1.5, 0.2, 48]} />
        <meshStandardMaterial color="#111114" metalness={0.8} roughness={0.25} />
      </mesh>
      {/* rak server */}
      {[0, 1, 2, 3].map((i) => (
        <RoundedBox key={i} args={[1.1, 0.34, 1.1]} radius={0.05} position={[0, 0.42 + i * 0.4, 0]}>
          <meshStandardMaterial color="#18181b" metalness={0.7} roughness={0.3} />
        </RoundedBox>
      ))}
      {/* inti hijau berpendar */}
      <mesh position={[0, 1.0, 0]}>
        <cylinderGeometry args={[0.18, 0.18, 1.5, 24]} />
        <meshStandardMaterial ref={core} color="#065f46" emissive={NEON} emissiveIntensity={2} toneMapped={false} />
      </mesh>
      {/* tabung kaca */}
      <mesh position={[0, 1.0, 0]}>
        <cylinderGeometry args={[0.85, 0.85, 1.9, 48, 1, true]} />
        <meshPhysicalMaterial color="#a7f3d0" transparent opacity={0.12} roughness={0.05} metalness={0} clearcoat={1} side={THREE.DoubleSide} />
      </mesh>
      <mesh ref={ring} position={[0, 2.05, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.95, 0.025, 12, 64]} />
        <meshStandardMaterial color="#10b981" emissive={NEON} emissiveIntensity={3} toneMapped={false} />
      </mesh>
      <pointLight ref={light} position={[0, 1.6, 0]} color="#10b981" distance={9} decay={1.6} />
      <Html position={[0, 2.55, 0]} center zIndexRange={[10, 0]}>
        <div className="pointer-events-none rounded-md border border-emerald-500/40 bg-black/70 px-2 py-0.5 font-mono text-[10px] tracking-widest whitespace-nowrap text-emerald-300 uppercase">
          AAGE Core · Orchestrator
        </div>
      </Html>
    </group>
  )
}

function Desk({ id, label, pos, color, activity, status }: (typeof DESKS)[number] & { activity: Activity; status?: string }) {
  const active = useActive(activity, id)
  const screen = useRef<THREE.MeshStandardMaterial>(null)
  const cube = useRef<THREE.MeshStandardMaterial>(null)
  const avatar = useRef<THREE.Group>(null)
  const c = useMemo(() => new THREE.Color(color), [color])
  useFrame(({ clock }) => {
    const a = active(performance.now())
    const t = clock.getElapsedTime()
    const flicker = a > 0.05 ? 0.7 + 0.3 * Math.sin(t * 22) : 1
    if (screen.current) screen.current.emissiveIntensity = 0.35 + a * 3.2 * flicker
    if (cube.current) cube.current.emissiveIntensity = 0.2 + a * 4 * flicker
    if (avatar.current) avatar.current.position.y = 0.55 + Math.sin(t * 2 + pos[0]) * 0.02 + a * 0.05
  })
  // Meja menghadap server pusat
  const rotY = Math.atan2(-pos[0], -pos[2])
  const isAlert = status === "BLOCKED"
  return (
    <group position={pos} rotation={[0, rotY, 0]}>
      {/* karpet zona */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]}>
        <circleGeometry args={[1.55, 48]} />
        <meshStandardMaterial color={color} transparent opacity={0.07} />
      </mesh>
      {/* meja */}
      <RoundedBox args={[1.9, 0.08, 0.95]} radius={0.03} position={[0, 0.78, 0.15]}>
        <meshPhysicalMaterial color="#d4d4d8" transparent opacity={0.35} roughness={0.1} clearcoat={1} />
      </RoundedBox>
      {[-0.85, 0.85].map((x) => (
        <mesh key={x} position={[x, 0.39, 0.15]}>
          <boxGeometry args={[0.06, 0.78, 0.85]} />
          <meshStandardMaterial color="#27272a" metalness={0.6} roughness={0.4} />
        </mesh>
      ))}
      {/* monitor */}
      <mesh position={[0, 1.18, 0.42]}>
        <boxGeometry args={[0.95, 0.56, 0.04]} />
        <meshStandardMaterial ref={screen} color="#052e24" emissive={c} emissiveIntensity={0.4} toneMapped={false} />
      </mesh>
      <mesh position={[0, 0.88, 0.45]}>
        <cylinderGeometry args={[0.03, 0.05, 0.18, 12]} />
        <meshStandardMaterial color="#3f3f46" />
      </mesh>
      {/* kubus komputer (berkedip saat agen memproses) */}
      <RoundedBox args={[0.32, 0.32, 0.32]} radius={0.04} position={[0.72, 0.99, 0.35]}>
        <meshStandardMaterial ref={cube} color="#0a0a0a" emissive={c} emissiveIntensity={0.3} toneMapped={false} />
      </RoundedBox>
      {/* kursi + avatar agen */}
      <mesh position={[0, 0.45, -0.55]}>
        <cylinderGeometry args={[0.32, 0.32, 0.08, 24]} />
        <meshStandardMaterial color="#18181b" />
      </mesh>
      <group ref={avatar} position={[0, 0.55, -0.55]}>
        <mesh position={[0, 0.32, 0]}>
          <capsuleGeometry args={[0.2, 0.32, 8, 16]} />
          <meshPhysicalMaterial color={color} transparent opacity={0.85} roughness={0.15} clearcoat={1} />
        </mesh>
        <mesh position={[0, 0.78, 0]}>
          <sphereGeometry args={[0.17, 24, 24]} />
          <meshPhysicalMaterial color="#e4e4e7" roughness={0.2} clearcoat={1} />
        </mesh>
      </group>
      <Html position={[0, 2.05, 0]} center zIndexRange={[10, 0]}>
        <div
          className={`pointer-events-none flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold whitespace-nowrap backdrop-blur ${
            isAlert ? "border-rose-500/70 bg-rose-950/80 text-rose-200" : "border-emerald-500/40 bg-zinc-950/80 text-zinc-100"
          }`}
        >
          <span className="size-1.5 rounded-full" style={{ background: isAlert ? "#f43f5e" : color, boxShadow: `0 0 8px ${isAlert ? "#f43f5e" : color}` }} />
          {label}
        </div>
      </Html>
    </group>
  )
}

/** Pipa data bercahaya (garis putus-putus yang mengalir) dari meja ke server. */
function DataPipe({ from, color, activity, id }: { from: [number, number, number]; color: string; activity: Activity; id: AgentId }) {
  const active = useActive(activity, id)
  const ref = useRef<{ material: THREE.Material & { dashOffset: number; opacity: number } } | null>(null)
  const points = useMemo(() => {
    const start = new THREE.Vector3(from[0] * 0.78, 1.0, from[2] * 0.78)
    const end = new THREE.Vector3(...SERVER_TOP)
    const mid = start.clone().lerp(end, 0.5).add(new THREE.Vector3(0, 1.1, 0))
    return new THREE.QuadraticBezierCurve3(start, mid, end).getPoints(40)
  }, [from])
  useFrame((_, dt) => {
    const a = active(performance.now())
    if (ref.current?.material) {
      ref.current.material.dashOffset -= dt * (0.4 + a * 3)
      ref.current.material.opacity = 0.25 + a * 0.75
    }
  })
  return (
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    <Line ref={ref as any} points={points} color={color} lineWidth={2} dashed dashSize={0.25} gapSize={0.18} transparent opacity={0.3} />
  )
}

/** Partikel cahaya dari meja aktif ke server pusat. */
function Particles({ activity }: { activity: Activity }) {
  const N = 14
  const meshes = useRef<(THREE.Mesh | null)[][]>(DESKS.map(() => Array(N).fill(null)))
  const curves = useMemo(
    () =>
      DESKS.map((d) => {
        const start = new THREE.Vector3(d.pos[0] * 0.78, 1.0, d.pos[2] * 0.78)
        const end = new THREE.Vector3(...SERVER_TOP)
        const mid = start.clone().lerp(end, 0.5).add(new THREE.Vector3(0, 1.1, 0))
        return new THREE.QuadraticBezierCurve3(start, mid, end)
      }),
    [],
  )
  const level = useRef(DESKS.map(() => 0))
  useFrame(({ clock }) => {
    const now = performance.now()
    const t = clock.getElapsedTime()
    DESKS.forEach((d, di) => {
      const target = now - (activity[d.id] ?? -1e9) < 1800 ? 1 : 0
      level.current[di] += (target - level.current[di]) * 0.1
      meshes.current[di].forEach((m, i) => {
        if (!m) return
        const p = (t * 0.55 + i / N) % 1
        m.position.copy(curves[di].getPoint(p))
        const s = level.current[di] * (0.6 + 0.4 * Math.sin(p * Math.PI))
        m.scale.setScalar(Math.max(0.0001, s))
      })
    })
  })
  return (
    <>
      {DESKS.map((d, di) =>
        Array.from({ length: N }).map((_, i) => (
          <mesh key={`${d.id}-${i}`} ref={(el) => (meshes.current[di][i] = el)}>
            <sphereGeometry args={[0.055, 10, 10]} />
            <meshBasicMaterial color={d.id === "claim_guard_agent" ? "#fda4af" : "#6ee7b7"} toneMapped={false} />
          </mesh>
        )),
      )}
    </>
  )
}

function Room() {
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <planeGeometry args={[16, 16]} />
        <meshStandardMaterial color="#0b0b0d" metalness={0.4} roughness={0.6} />
      </mesh>
      <Grid position={[0, 0.005, 0]} args={[16, 16]} cellSize={0.5} cellThickness={0.5} cellColor="#1f2937" sectionSize={2}
        sectionThickness={1} sectionColor="#065f46" fadeDistance={30} infiniteGrid={false} />
      {/* dinding kaca belakang */}
      <mesh position={[0, 1.6, -8]}>
        <boxGeometry args={[16, 3.2, 0.06]} />
        <meshPhysicalMaterial color="#10b981" transparent opacity={0.06} roughness={0.05} clearcoat={1} />
      </mesh>
      <mesh position={[-8, 1.6, 0]}>
        <boxGeometry args={[0.06, 3.2, 16]} />
        <meshPhysicalMaterial color="#10b981" transparent opacity={0.06} roughness={0.05} clearcoat={1} />
      </mesh>
      {/* list neon lantai */}
      {[
        [[-8, 0.02, -8], [8, 0.02, -8]],
        [[-8, 0.02, -8], [-8, 0.02, 8]],
      ].map((pts, i) => (
        <Line key={i} points={pts as [number, number, number][]} color="#10b981" lineWidth={2} transparent opacity={0.6} />
      ))}
    </group>
  )
}

export default function OfficeScene({ activity, statuses }: { activity: Activity; statuses: Partial<Record<AgentId, string>> }) {
  const busy = Object.values(activity).some((t) => (t ? performance.now() - t < 1800 : false)) ? 1 : 0
  return (
    <Canvas dpr={[1, 1.75]} shadows={false} gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping }}>
      <color attach="background" args={["#060607"]} />
      <fog attach="fog" args={["#060607", 22, 40]} />
      <OrthographicCamera makeDefault position={[11, 10, 11]} zoom={56} near={0.1} far={100} onUpdate={(cam) => cam.lookAt(0, 0.8, 0)} />
      <OrbitControls enableDamping dampingFactor={0.08} minZoom={28} maxZoom={110} maxPolarAngle={Math.PI / 2.3} target={[0, 0.8, 0]} />
      <ambientLight intensity={0.35} />
      <directionalLight position={[6, 10, 4]} intensity={0.9} color="#ecfdf5" />
      <hemisphereLight args={["#34d399", "#09090b", 0.25]} />
      <Room />
      <ServerCore busy={busy} />
      {DESKS.map((d) => (
        <group key={d.id}>
          <Desk {...d} activity={activity} status={statuses[d.id]} />
          <DataPipe from={d.pos} color={d.color} activity={activity} id={d.id} />
        </group>
      ))}
      <Particles activity={activity} />
    </Canvas>
  )
}
