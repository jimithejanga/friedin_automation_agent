"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Search, Clock, ArrowRight, AlertCircle, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";

export default function TrackPage() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recentCases, setRecentCases] = useState<Array<{ id: string; case_number: string; subject: string; created_at: string }>>([]);

  useEffect(() => {
    try {
      const stored = localStorage.getItem("cmr_recent_cases");
      if (stored) {
        setRecentCases(JSON.parse(stored));
      }
    } catch {
      // ignore
    }
  }, []);

  const handleLookup = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanId = identifier.trim();
    if (!cleanId) return;

    setLoading(true);
    setError(null);

    // Check if UUID
    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(cleanId);
    if (isUuid) {
      router.push(`/cases/${cleanId}`);
      return;
    }

    // Otherwise lookup by case_number
    try {
      const foundCase = await api.lookupCase(cleanId);
      router.push(`/cases/${foundCase.id}`);
    } catch (err: any) {
      setError(err.message || `No case found matching '${cleanId}'. Check the number and try again.`);
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: "3rem 0 5rem" }}>
      <div className="portal-container" style={{ maxWidth: "680px" }}>
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: "2.5rem" }}>
          <div
            style={{
              width: "48px",
              height: "48px",
              borderRadius: "12px",
              background: "#ecfdf5",
              color: "#059669",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "0 auto 1rem",
            }}
          >
            <Search size={24} />
          </div>
          <h1 style={{ fontSize: "2rem", fontWeight: 800, color: "#064e3b", letterSpacing: "-0.02em" }}>
            Track Case Status & Timeline
          </h1>
          <p style={{ color: "#475569", fontSize: "0.95rem" }}>
            Enter your official Central Motor Registry Case Number (e.g. CMR-20260905-XXXX) or Case ID.
          </p>
        </div>

        {/* Search Panel */}
        <div className="glass-panel" style={{ padding: "2rem", background: "#ffffff", marginBottom: "2rem" }}>
          <form onSubmit={handleLookup}>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 700, color: "#0f172a", marginBottom: "0.5rem" }}>
              Case Number or UUID
            </label>
            <div style={{ display: "flex", gap: "0.75rem", marginBottom: "1rem" }}>
              <input
                type="text"
                placeholder="e.g. CMR-20260905-A1B2 or 9a38f6b4-..."
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                style={{
                  flex: 1,
                  padding: "0.85rem 1rem",
                  borderRadius: "8px",
                  border: "1px solid #cbd5e1",
                  fontSize: "1rem",
                  letterSpacing: "0.02em",
                }}
              />
              <button type="submit" disabled={loading || !identifier.trim()} className="btn-primary" style={{ padding: "0.85rem 1.75rem" }}>
                {loading ? "Searching..." : "Track"}
              </button>
            </div>
          </form>

          {error && (
            <div
              style={{
                background: "#fef2f2",
                border: "1px solid #fecaca",
                color: "#b91c1c",
                padding: "0.85rem",
                borderRadius: "8px",
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                fontSize: "0.88rem",
              }}
            >
              <AlertCircle size={18} />
              <span>{error}</span>
            </div>
          )}
        </div>

        {/* Recent Cases on this device */}
        {recentCases.length > 0 && (
          <div className="glass-panel" style={{ padding: "1.5rem", background: "#ffffff" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.4rem", fontSize: "0.85rem", fontWeight: 700, color: "#064e3b", marginBottom: "1rem" }}>
              <Clock size={16} />
              <span>Recent Cases Looked Up on This Device:</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              {recentCases.map((c) => (
                <Link
                  key={c.id}
                  href={`/cases/${c.id}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.75rem 1rem",
                    borderRadius: "8px",
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    transition: "all 0.15s ease",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = "#059669")}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = "#e2e8f0")}
                >
                  <div>
                    <div style={{ fontWeight: 700, fontSize: "0.9rem", color: "#0f172a" }}>{c.case_number}</div>
                    <div style={{ fontSize: "0.8rem", color: "#64748b" }}>{c.subject}</div>
                  </div>
                  <ArrowRight size={16} color="#059669" />
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
