import React from "react";
import { ShieldCheck } from "lucide-react";

export default function Footer() {
  return (
    <footer
      style={{
        marginTop: "auto",
        borderTop: "1px solid #e2e8f0",
        background: "#ffffff",
        padding: "2.5rem 0",
        color: "#64748b",
        fontSize: "0.85rem",
      }}
    >
      <div className="portal-container" style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: "1.5rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <div
            style={{
              width: "32px",
              height: "32px",
              borderRadius: "8px",
              background: "#064e3b",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#ffffff",
            }}
          >
            <ShieldCheck size={18} />
          </div>
          <div>
            <div style={{ fontWeight: 700, color: "#0f172a" }}>
              Nigeria Central Motor Registry (CMR) Specialist
            </div>
            <div style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
              Federal Motor Vehicle Administration & Intelligence Portal
            </div>
          </div>
        </div>

        <div style={{ display: "flex", gap: "1.5rem", fontSize: "0.8rem" }}>
          <span>Emergency Support: 0800-CMR-HELP</span>
          <span>•</span>
          <span>FastAPI v1.0.0</span>
          <span>•</span>
          <span>AI Version: Strict Active Retrieval</span>
        </div>

        <div style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
          © {new Date().getFullYear()} Federal Republic of Nigeria. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
