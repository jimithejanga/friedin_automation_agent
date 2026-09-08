"use client";

import React from "react";
import { CitationSchema } from "@/lib/types";
import { X, BookOpen, CheckCircle, ExternalLink } from "lucide-react";

interface CitationModalProps {
  citation: CitationSchema | null;
  onClose: () => void;
}

export default function CitationModal({ citation, onClose }: CitationModalProps) {
  if (!citation) return null;

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
          maxWidth: "560px",
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
                background: "#ecfdf5",
                color: "#059669",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <BookOpen size={20} />
            </div>
            <div>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, textTransform: "uppercase", color: "#059669" }}>
                Active Vector Citation
              </div>
              <h3 style={{ fontSize: "1.1rem", fontWeight: 700, color: "#0f172a" }}>
                {citation.document_title}
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

        {/* Verification Status */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            background: "#f0fdf4",
            border: "1px solid #bbf7d0",
            padding: "0.6rem 0.85rem",
            borderRadius: "8px",
            fontSize: "0.8rem",
            color: "#166534",
            marginBottom: "1.25rem",
          }}
        >
          <CheckCircle size={16} />
          <span>
            Verified from <strong>ACTIVE</strong> Published Document Version
          </span>
        </div>

        {/* Chunk Identifier */}
        {citation.chunk_id && (
          <div style={{ marginBottom: "1rem", fontSize: "0.8rem", color: "#64748b" }}>
            <span style={{ fontWeight: 600 }}>Chunk ID: </span>
            <code style={{ background: "#f1f5f9", padding: "0.15rem 0.4rem", borderRadius: "4px", color: "#0f172a" }}>
              {citation.chunk_id}
            </code>
          </div>
        )}

        {/* Excerpt */}
        <div style={{ marginBottom: "1.5rem" }}>
          <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#475569", marginBottom: "0.4rem" }}>
            Source Text Excerpt:
          </div>
          <div
            style={{
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              borderLeft: "4px solid #059669",
              padding: "1rem",
              borderRadius: "6px",
              fontSize: "0.88rem",
              lineHeight: 1.6,
              color: "#334155",
              maxHeight: "220px",
              overflowY: "auto",
              fontStyle: "italic",
            }}
          >
            &ldquo;{citation.excerpt || "Official procedural text chunk retrieved via vector similarity search."}&rdquo;
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem" }}>
          {citation.source_url && (
            <a
              href={citation.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-secondary"
              style={{ fontSize: "0.85rem", padding: "0.5rem 1rem" }}
            >
              <ExternalLink size={14} />
              Open Source
            </a>
          )}
          <button onClick={onClose} className="btn-primary" style={{ fontSize: "0.85rem", padding: "0.5rem 1.25rem" }}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
