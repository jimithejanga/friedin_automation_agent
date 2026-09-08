"use client";

import React, { useEffect, useState } from "react";
import { AIRunDetailResponse } from "@/lib/types";
import { api } from "@/lib/api";
import { X, Cpu, CheckCircle, ShieldAlert, Clock, Layers } from "lucide-react";
import { formatDate } from "@/lib/utils";

interface AIRunModalProps {
  runId: string | null;
  onClose: () => void;
}

export default function AIRunModal({ runId, onClose }: AIRunModalProps) {
  const [trace, setTrace] = useState<AIRunDetailResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    setError(null);
    api
      .getAIRunTrace(runId)
      .then((res) => setTrace(res))
      .catch((err) => setError(err.message || "Failed to load trace"))
      .finally(() => setLoading(false));
  }, [runId]);

  if (!runId) return null;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        backgroundColor: "rgba(15, 23, 42, 0.6)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: "1rem",
      }}
      onClick={onClose}
    >
      <div
        className="glass-panel animate-fade-in"
        style={{
          width: "100%",
          maxWidth: "680px",
          maxHeight: "90vh",
          overflowY: "auto",
          background: "#ffffff",
          padding: "1.75rem",
          position: "relative",
          boxShadow: "0 20px 25px -5px rgba(0, 0, 0, 0.2)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1.25rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
            <div
              style={{
                width: "36px",
                height: "36px",
                borderRadius: "8px",
                background: "#f5f3ff",
                color: "#7c3aed",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Cpu size={20} />
            </div>
            <div>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, textTransform: "uppercase", color: "#7c3aed" }}>
                Execution Transparency Trace
              </div>
              <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>
                AIRun Verification Record
              </h3>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: "#94a3b8",
              padding: "0.25rem",
              borderRadius: "4px",
            }}
          >
            <X size={20} />
          </button>
        </div>

        {loading && (
          <div style={{ textAlign: "center", padding: "2rem", color: "#64748b" }}>
            Fetching verified execution record...
          </div>
        )}

        {error && (
          <div style={{ background: "#fef2f2", color: "#b91c1c", padding: "1rem", borderRadius: "8px" }}>
            {error}
          </div>
        )}

        {trace && (
          <div>
            {/* Metadata Grid */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                gap: "0.75rem",
                marginBottom: "1.25rem",
              }}
            >
              <div style={{ background: "#f8fafc", padding: "0.75rem", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.7rem", color: "#64748b", fontWeight: 600 }}>MODEL</div>
                <div style={{ fontWeight: 700, fontSize: "0.9rem", color: "#0f172a" }}>{trace.model_name}</div>
              </div>
              <div style={{ background: "#f8fafc", padding: "0.75rem", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.7rem", color: "#64748b", fontWeight: 600 }}>INTENT</div>
                <div style={{ fontWeight: 700, fontSize: "0.9rem", color: trace.intent === "INFORMATIONAL" ? "#047857" : "#c2410c" }}>
                  {trace.intent}
                </div>
              </div>
              <div style={{ background: "#f8fafc", padding: "0.75rem", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.7rem", color: "#64748b", fontWeight: 600 }}>LATENCY</div>
                <div style={{ fontWeight: 700, fontSize: "0.9rem", color: "#0f172a" }}>{trace.latency_ms.toFixed(1)} ms</div>
              </div>
              <div style={{ background: "#f8fafc", padding: "0.75rem", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                <div style={{ fontSize: "0.7rem", color: "#64748b", fontWeight: 600 }}>TOTAL TOKENS</div>
                <div style={{ fontWeight: 700, fontSize: "0.9rem", color: "#0f172a" }}>{trace.total_tokens}</div>
              </div>
            </div>

            {/* Guardrail & Boundary Status */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "0.75rem 1rem",
                borderRadius: "8px",
                background: trace.guardrail_triggered ? "#fffbeb" : "#f0fdf4",
                border: `1px solid ${trace.guardrail_triggered ? "#fde68a" : "#bbf7d0"}`,
                marginBottom: "1.25rem",
                fontSize: "0.85rem",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                {trace.guardrail_triggered ? (
                  <ShieldAlert size={18} color="#b45309" />
                ) : (
                  <CheckCircle size={18} color="#15803d" />
                )}
                <span style={{ fontWeight: 600, color: trace.guardrail_triggered ? "#b45309" : "#15803d" }}>
                  {trace.guardrail_triggered ? "Safety Guardrail Triggered" : "Safety Guardrails Cleared"}
                </span>
              </div>
              <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
                Template: v{trace.prompt_template_version}
              </div>
            </div>

            {/* Retrieved Chunks */}
            <div style={{ marginBottom: "1.25rem" }}>
              <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#0f172a", marginBottom: "0.5rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                <Layers size={16} color="#475569" />
                Retrieved Vector Chunks ({trace.retrieved_chunks.length})
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", maxHeight: "180px", overflowY: "auto" }}>
                {trace.retrieved_chunks.map((chunk, idx) => (
                  <div
                    key={idx}
                    style={{
                      background: "#f8fafc",
                      border: "1px solid #e2e8f0",
                      padding: "0.6rem 0.8rem",
                      borderRadius: "6px",
                      fontSize: "0.8rem",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 600, color: "#334155", marginBottom: "0.25rem" }}>
                      <span>Doc: {chunk.document_title || "Unknown Document"}</span>
                      {chunk.similarity !== undefined && (
                        <span style={{ color: "#059669" }}>Cosine: {(chunk.similarity * 100).toFixed(1)}%</span>
                      )}
                    </div>
                    <div style={{ color: "#64748b", fontStyle: "italic", fontSize: "0.75rem" }}>
                      &ldquo;{(chunk.text || "").slice(0, 140)}...&rdquo;
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ fontSize: "0.75rem", color: "#94a3b8", display: "flex", justifyContent: "space-between", borderTop: "1px solid #e2e8f0", paddingTop: "0.75rem" }}>
              <span>Run ID: {trace.id}</span>
              <span>Executed: {formatDate(trace.created_at)}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
