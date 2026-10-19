"use client"

// Orb kaca cair emerald (design.md §10). Di-lazy-load lewat next/dynamic (ssr:false),
// dpr [1, 1.5], berhenti render saat tidak terlihat, parallax kursor ±6°.

import { Environment, Float, Lightformer, MeshTransmissionMaterial } from "@react-three/drei"
import { Canvas, useFrame } from "@react-three/fiber"
import { useEffect, useMemo, useRef, useState } from "react"
import { CanvasTexture, type Group, type Points } from "three"

import { StaticOrb } from "./StaticOrb"

/** Halo gradient di belakang orb: memberi cahaya emerald/champagne untuk dibiaskan kaca. */
function Halo() {
  const texture = useMemo(() => {
    const c = document.createElement("canvas")
    c.width = c.height = 256
    const ctx = c.getContext("2d")!
    const g = ctx.createRadialGradient(128, 128, 0, 128, 128, 128)
    g.addColorStop(0, "rgba(167,243,208,0.95)")
    g.addColorStop(0.3, "rgba(22,163,122,0.7)")
    g.addColorStop(0.52, "rgba(230,211,168,0.12)")
    g.addColorStop(0.7, "rgba(6,37,28,0)")
    ctx.fillStyle = g
    ctx.fillRect(0, 0, 256, 256)
    return new CanvasTexture(c)
  }, [])
  return (
    <mesh position={[0.35, 0.25, -2.2]}>
      <planeGeometry args={[6.5, 6.5]} />
      <meshBasicMaterial map={texture} transparent depthWrite={false} />
    </mesh>
  )
}

function Orb() {
  const group = useRef<Group>(null)
  useFrame((state) => {
    if (!group.current) return
    const max = (6 * Math.PI) / 180
    group.current.rotation.y += (state.pointer.x * max - group.current.rotation.y) * 0.05
    group.current.rotation.x += (-state.pointer.y * max - group.current.rotation.x) * 0.05
  })
  return (
    <group ref={group}>
      <Float speed={1.2} rotationIntensity={0.25} floatIntensity={0.8}>
        <mesh>
          <icosahedronGeometry args={[1.25, 32]} />
          <MeshTransmissionMaterial
            transmission={1}
            thickness={0.6}
            roughness={0.15}
            chromaticAberration={0.03}
            color="#16A37A"
            distortion={0.3}
            distortionScale={0.4}
            temporalDistortion={0.2}
            ior={1.3}
            backside
            samples={6}
            resolution={256}
          />
        </mesh>
      </Float>
    </group>
  )
}

function DataParticles({ count = 70 }: { count?: number }) {
  const ref = useRef<Points>(null)
  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const r = 1.8 + Math.random() * 0.9
      const t = Math.random() * Math.PI * 2
      const y = (Math.random() - 0.5) * 1.6
      arr[i * 3] = Math.cos(t) * r
      arr[i * 3 + 1] = y
      arr[i * 3 + 2] = Math.sin(t) * r
    }
    return arr
  }, [count])
  useFrame((_, delta) => {
    if (ref.current) ref.current.rotation.y += delta * 0.12
  })
  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial size={0.035} color="#A7F3D0" transparent opacity={0.85} sizeAttenuation />
    </points>
  )
}

function webglAvailable() {
  try {
    const c = document.createElement("canvas")
    return Boolean(c.getContext("webgl2") || c.getContext("webgl"))
  } catch {
    return false
  }
}

export default function LiquidOrb({ className = "" }: { className?: string }) {
  const wrap = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<"pending" | "3d" | "static">("pending")
  const [visible, setVisible] = useState(true)

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    const weak = (navigator.hardwareConcurrency ?? 8) <= 2
    setMode(!reduce && !weak && webglAvailable() ? "3d" : "static")
  }, [])

  useEffect(() => {
    if (!wrap.current) return
    const io = new IntersectionObserver(([e]) => setVisible(e.isIntersecting && document.visibilityState === "visible"))
    io.observe(wrap.current)
    const onVis = () => setVisible(document.visibilityState === "visible")
    document.addEventListener("visibilitychange", onVis)
    return () => {
      io.disconnect()
      document.removeEventListener("visibilitychange", onVis)
    }
  }, [])

  return (
    <div ref={wrap} className={`relative aspect-square ${className}`}>
      {mode !== "3d" ? (
        <StaticOrb className="h-full w-full" />
      ) : (
        <Canvas dpr={[1, 1.5]} frameloop={visible ? "always" : "never"} camera={{ position: [0, 0, 5], fov: 40 }} gl={{ antialias: true, alpha: true }}>
          <ambientLight intensity={0.6} />
          <directionalLight position={[3, 4, 2]} intensity={1.2} color="#E6D3A8" />
          <Halo />
          <Orb />
          <DataParticles />
          <Environment resolution={256}>
            <Lightformer form="ring" intensity={2.2} color="#E6D3A8" position={[2, 2, 3]} scale={2.5} />
            <Lightformer form="rect" intensity={1.6} color="#A7F3D0" position={[-3, 1, 2]} scale={[4, 1, 1]} />
            <Lightformer form="rect" intensity={1} color="#ffffff" position={[0, -3, 2]} scale={[6, 1, 1]} />
          </Environment>
        </Canvas>
      )}
    </div>
  )
}
