"use client";

import React, { use, useEffect, useState } from "react";
import Link from "next/link";
import { Cpu, CheckCircle, ShieldAlert, ArrowLeft, Layers, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { AIRunDetailResponse } from "@/lib/types";
import { formatDate } from "@/lib/utils";

export default function TracePage({ params }: { params: Promise<{ runId: string }> }) {
  const resolvedParams = use(params);
  const runId = resolvedParams.runId;

  const [trace, setTrace] = useState<AIRunDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getAIRunTrace(runId)
      .then((res) => setTrace(res))
      .catch((err) => setError(err.message || "Failed to fetch trace"))
      .finally(() => setLoading(false));
  }, [runId]);

  return (
    <div style={{ padding: "3rem 0 5rem" }}>
      <div className="portal-container" style={{ maxWidth: "760px" }}>
        <Link
          href="/"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.4rem",
            color: "#059669",
            fontSize: "0.85rem",
            fontWeight: 600,
            marginBottom: "1.5rem",
          }}
        >
          <ArrowLeft size={16} />
          <span>Back to Ingestion Portal</span>
        </Link>

        {loading && (
          <div style={{ textAlign: "center", padding: "4rem", color: "#64748b" }}>
            Loading AI execution verification trace...
          </div>
        )}

        {error && (
          <div style={{ background: "#fef2f2", color: "#b91c1c", padding: "1.5rem", borderRadius: "10px" }}>
            {error}
          </div>
        )}

        {trace && (
          <div className="glass-panel" style={{ padding: "2rem", background: "#ffffff" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "1.5rem" }}>
              <div
                style={{
                  width: "44px",
                  height: "44px",
                  borderRadius: "10px",
                  background: "#f5f3ff",
                  color: "#7c3aed",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
              >
                <Cpu size={24} />
              </div>
              <div>
                <h1 style={{ fontSize: "1.35rem", fontWeight: 800, color: "#0f172a" }}>
                  AI Verification & Grounding Trace
                </h1>
                <div style={{ fontSize: "0.8rem", color: "#64748b" }}>
                  Immutable record from Phase 5 Traceability Architecture
                </div>
              </div>
            </div>

            {/* Metrics */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                gap: "0.75rem",
                marginBottom: "1.5rem",
              }}
            >
              <div style={{ background: "#f8fafc", padding: "0.85rem", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.7rem", color: "#64748b", fontWeight: 600 }}>MODEL</div>
                <div style={{ fontWeight: 700, fontSize: "0.95rem" }}>{trace.model_name}</div>
              </div>
              <div style={{ background: "#f8fafc", padding: "0.85rem", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.7rem", color: "#64748b", fontWeight: 600 }}>INTENT</div>
                <div style={{ fontWeight: 700, fontSize: "0.95rem", color: "#059669" }}>{trace.intent}</div>
              </div>
              <div style={{ background: "#f8fafc", padding: "0.85rem", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.7rem", color: "#64748b", fontWeight: 600 }}>LATENCY</div>
                <div style={{ fontWeight: 700, fontSize: "0.95rem" }}>{trace.latency_ms.toFixed(1)} ms</div>
              </div>
              <div style={{ background: "#f8fafc", padding: "0.85rem", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.7rem", color: "#64748b", fontWeight: 600 }}>TOKENS</div>
                <div style={{ fontWeight: 700, fontSize: "0.95rem" }}>{trace.total_tokens}</div>
              </div>
            </div>

            {/* Answer and Query */}
            <div style={{ marginBottom: "1.5rem" }}>
              <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#64748b", marginBottom: "0.25rem" }}>CUSTOMER QUERY</div>
              <div style={{ background: "#f8fafc", padding: "0.85rem", borderRadius: "8px", fontSize: "0.9rem", color: "#1e293b", marginBottom: "1rem" }}>
                {trace.query_text}
              </div>

              <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#64748b", marginBottom: "0.25rem" }}>SYNTHESIZED ANSWER</div>
              <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "1rem", borderRadius: "8px", fontSize: "0.95rem", lineHeight: 1.6, color: "#064e3b" }}>
                {trace.answer_text}
              </div>
            </div>

            {/* Retrieved Chunks */}
            <div style={{ marginBottom: "1.5rem" }}>
              <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#0f172a", marginBottom: "0.5rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                <Layers size={16} />
                Retrieved Vector Chunks ({trace.retrieved_chunks.length})
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                {trace.retrieved_chunks.map((chunk, idx) => (
                  <div key={idx} style={{ background: "#f8fafc", border: "1px solid #e2e8f0", padding: "0.75rem", borderRadius: "6px", fontSize: "0.8rem" }}>
                    <div style={{ fontWeight: 600, color: "#059669", marginBottom: "0.25rem" }}>{chunk.document_title}</div>
                    <div style={{ color: "#475569", fontStyle: "italic" }}>&ldquo;{chunk.text}&rdquo;</div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ fontSize: "0.75rem", color: "#94a3b8", borderTop: "1px solid #f1f5f9", paddingTop: "1rem", display: "flex", justifyContent: "space-between" }}>
              <span>Trace ID: {trace.id}</span>
              <span>Executed: {formatDate(trace.created_at)}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
