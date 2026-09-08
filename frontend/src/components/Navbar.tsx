"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ShieldCheck, Search, PlusCircle, HelpCircle, Activity } from "lucide-react";
import { api } from "@/lib/api";

export default function Navbar() {
  const pathname = usePathname();
  const [backendOk, setBackendOk] = useState<boolean | null>(null);

  useEffect(() => {
    let isMounted = true;
    const verifyHealth = () => {
      api
        .checkHealth()
        .then((res) => {
          if (isMounted) setBackendOk(res.status === "ok");
        })
        .catch(() => {
          if (isMounted) setBackendOk(false);
        });
    };

    verifyHealth();
    const interval = setInterval(verifyHealth, 4000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  const navLinks = [
    { href: "/", label: "AI Ingestion & Inquiry", icon: HelpCircle },
    { href: "/open-case", label: "Open Official Case", icon: PlusCircle },
    { href: "/track", label: "Track Case Status", icon: Search },
  ];

  return (
    <header style={{ borderBottom: "1px solid #e2e8f0", background: "rgba(255, 255, 255, 0.95)", backdropFilter: "blur(12px)", position: "sticky", top: 0, zIndex: 50 }}>
      <div className="portal-container" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", height: "70px" }}>
        {/* Brand */}
        <Link href="/" style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <div
            style={{
              width: "42px",
              height: "42px",
              borderRadius: "10px",
              background: "linear-gradient(135deg, #064e3b 0%, #047857 100%)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#ffffff",
              boxShadow: "0 4px 10px rgba(6, 78, 59, 0.2)",
            }}
          >
            <ShieldCheck size={26} />
          </div>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <span style={{ fontWeight: 800, fontSize: "1.1rem", letterSpacing: "-0.02em", color: "#064e3b" }}>
                CMR
              </span>
              <span style={{ fontSize: "0.75rem", fontWeight: 700, background: "#ecfdf5", color: "#047857", padding: "0.15rem 0.45rem", borderRadius: "4px", border: "1px solid #a7f3d0" }}>
                AUTOMATION AGENT
              </span>
            </div>
            <div style={{ fontSize: "0.75rem", color: "#64748b", fontWeight: 500 }}>
              Central Motor Registry Specialist
            </div>
          </div>
        </Link>

        {/* Navigation */}
        <nav style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
          {navLinks.map((link) => {
            const Icon = link.icon;
            const isActive = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.4rem",
                  padding: "0.5rem 0.9rem",
                  borderRadius: "8px",
                  fontSize: "0.88rem",
                  fontWeight: 600,
                  color: isActive ? "#064e3b" : "#475569",
                  background: isActive ? "#ecfdf5" : "transparent",
                  border: isActive ? "1px solid #a7f3d0" : "1px solid transparent",
                  transition: "all 0.15s ease",
                }}
              >
                <Icon size={16} color={isActive ? "#059669" : "#64748b"} />
                {link.label}
              </Link>
            );
          })}
        </nav>

        {/* Backend Status Indicator */}
        <div
          title={backendOk === true ? "FastAPI Backend Connected" : backendOk === false ? "FastAPI Backend Offline" : "Checking Backend Status..."}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.4rem",
            fontSize: "0.75rem",
            fontWeight: 600,
            padding: "0.35rem 0.75rem",
            borderRadius: "9999px",
            background: backendOk === true ? "#f0fdf4" : backendOk === false ? "#fef2f2" : "#f8fafc",
            border: `1px solid ${backendOk === true ? "#bbf7d0" : backendOk === false ? "#fecaca" : "#e2e8f0"}`,
            color: backendOk === true ? "#15803d" : backendOk === false ? "#b91c1c" : "#64748b",
          }}
        >
          <span
            style={{
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              background: backendOk === true ? "#22c55e" : backendOk === false ? "#ef4444" : "#94a3b8",
              display: "inline-block",
            }}
            className={backendOk === true ? "animate-pulse-glow" : ""}
          />
          <span>{backendOk === true ? "API Active" : backendOk === false ? "API Offline" : "Connecting"}</span>
        </div>
      </div>
    </header>
  );
}
