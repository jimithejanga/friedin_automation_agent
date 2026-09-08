"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Search,
  Sparkles,
  ArrowRight,
  ShieldCheck,
  CheckCircle2,
  FileText,
  AlertTriangle,
  Info,
  Clock,
  Car,
  User,
} from "lucide-react";
import { api } from "@/lib/api";
import { CitationSchema, QuestionResponse } from "@/lib/types";
import CitationModal from "@/components/CitationModal";
import AIRunModal from "@/components/AIRunModal";

const SUGGESTED_QUESTIONS = [
  "What are the requirements for tinted glass permit in Lagos?",
  "How do I process change of ownership for a purchased vehicle?",
  "What should I do if my engine number does not match my CMR certificate?",
  "How can I verify customized number plate validity?",
];

export default function HomePage() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [fullName, setFullName] = useState("");
  const [showIdentity, setShowIdentity] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<QuestionResponse | null>(null);

  const [selectedCitation, setSelectedCitation] = useState<CitationSchema | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  const handleAsk = async (textToAsk?: string) => {
    const questionText = textToAsk || query;
    if (!questionText.trim()) return;

    setLoading(true);
    setError(null);

    try {
      const response = await api.askQuestion({
        question: questionText,
        full_name: fullName.trim() || undefined,
        phone_number: phoneNumber.trim() || undefined,
        channel: "web",
      });
      setResult(response);
    } catch (err: any) {
      setError(err.message || "Failed to get AI answer from server");
    } finally {
      setLoading(false);
    }
  };

  const handleEscalateToCase = () => {
    if (!result) return;
    const params = new URLSearchParams();
    if (result.conversation_id) params.set("conversation_id", result.conversation_id);
    if (result.suggested_subject) params.set("subject", result.suggested_subject);
    if (result.suggested_category) params.set("category", result.suggested_category);
    if (fullName) params.set("full_name", fullName);
    if (phoneNumber) params.set("phone_number", phoneNumber);

    // Pass any extracted facts
    result.extracted_facts.forEach((f) => {
      params.set(`fact_${f.fact_key}`, f.fact_value);
    });

    router.push(`/open-case?${params.toString()}`);
  };

  return (
    <div className="hero-glow" style={{ padding: "3rem 0 5rem" }}>
      <div className="portal-container" style={{ maxWidth: "880px" }}>
        {/* Hero Header */}
        <div style={{ textAlign: "center", marginBottom: "2.5rem" }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.5rem",
              background: "#ecfdf5",
              color: "#047857",
              border: "1px solid #a7f3d0",
              padding: "0.35rem 0.85rem",
              borderRadius: "9999px",
              fontSize: "0.8rem",
              fontWeight: 700,
              marginBottom: "1rem",
            }}
          >
            <Sparkles size={16} />
            <span>AI-GROUNDED SPECIALIST INGESTION</span>
          </div>
          <h1
            style={{
              fontSize: "2.5rem",
              fontWeight: 800,
              letterSpacing: "-0.03em",
              color: "#064e3b",
              lineHeight: 1.15,
              marginBottom: "0.75rem",
            }}
          >
            Central Motor Registry Specialist
          </h1>
          <p
            style={{
              fontSize: "1.05rem",
              color: "#475569",
              maxWidth: "640px",
              margin: "0 auto",
              lineHeight: 1.6,
            }}
          >
            Get instant grounded procedural answers citing official CMR regulations, or open a tracked official case with automatic vehicle fact extraction.
          </p>
        </div>

        {/* Search & Inquiry Panel */}
        <div
          className="glass-panel"
          style={{
            padding: "1.75rem",
            marginBottom: "2rem",
            background: "#ffffff",
          }}
        >
          {/* Identity Bar Toggle */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <span style={{ fontSize: "0.85rem", fontWeight: 700, color: "#0f172a" }}>
              Inquire or Report an Issue
            </span>
            <button
              onClick={() => setShowIdentity(!showIdentity)}
              style={{
                background: "transparent",
                border: "none",
                fontSize: "0.8rem",
                color: "#059669",
                fontWeight: 600,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                gap: "0.3rem",
              }}
            >
              <User size={14} />
              {showIdentity ? "Hide Identity Fields" : "+ Add Contact (Phone/Name)"}
            </button>
          </div>

          {showIdentity && (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gap: "1rem",
                background: "#f8fafc",
                padding: "1rem",
                borderRadius: "8px",
                marginBottom: "1rem",
                border: "1px solid #e2e8f0",
              }}
            >
              <div>
                <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "#475569", marginBottom: "0.25rem" }}>
                  Full Name (Optional)
                </label>
                <input
                  type="text"
                  placeholder="e.g. Babatunde Adeyemi"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  style={{
                    width: "100%",
                    padding: "0.55rem 0.75rem",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    fontSize: "0.85rem",
                  }}
                />
              </div>
              <div>
                <label style={{ display: "block", fontSize: "0.75rem", fontWeight: 600, color: "#475569", marginBottom: "0.25rem" }}>
                  Phone Number (For Case Linking)
                </label>
                <input
                  type="tel"
                  placeholder="e.g. +2348012345678"
                  value={phoneNumber}
                  onChange={(e) => setPhoneNumber(e.target.value)}
                  style={{
                    width: "100%",
                    padding: "0.55rem 0.75rem",
                    borderRadius: "6px",
                    border: "1px solid #cbd5e1",
                    fontSize: "0.85rem",
                  }}
                />
              </div>
            </div>
          )}

          {/* Main Textarea */}
          <div style={{ position: "relative", marginBottom: "1rem" }}>
            <textarea
              rows={3}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask a question or explain your vehicle issue (e.g. 'I bought a vehicle with plate LAG-492-AA and need to verify the tint permit regulations in Lagos')..."
              style={{
                width: "100%",
                padding: "1rem",
                borderRadius: "10px",
                border: "1px solid #cbd5e1",
                fontSize: "0.95rem",
                lineHeight: 1.5,
                outline: "none",
                resize: "vertical",
                fontFamily: "inherit",
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  handleAsk();
                }
              }}
            />
          </div>

          {/* Submit Button & Shortcut hint */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
              Press <kbd style={{ background: "#f1f5f9", padding: "0.15rem 0.35rem", borderRadius: "4px" }}>Ctrl+Enter</kbd> to submit
            </div>
            <button
              onClick={() => handleAsk()}
              disabled={loading || !query.trim()}
              className="btn-primary"
            >
              {loading ? (
                <>
                  <div
                    style={{
                      width: "16px",
                      height: "16px",
                      border: "2px solid #ffffff",
                      borderTopColor: "transparent",
                      borderRadius: "50%",
                      animation: "spin 0.8s linear infinite",
                    }}
                  />
                  <span>Routing & Synthesizing...</span>
                </>
              ) : (
                <>
                  <Search size={18} />
                  <span>Consult Specialist</span>
                </>
              )}
            </button>
          </div>

          {/* Quick Preset Chips */}
          <div style={{ marginTop: "1.25rem", borderTop: "1px solid #f1f5f9", paddingTop: "1rem" }}>
            <div style={{ fontSize: "0.75rem", fontWeight: 600, color: "#64748b", marginBottom: "0.5rem" }}>
              Popular Inquiries:
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
              {SUGGESTED_QUESTIONS.map((q, idx) => (
                <button
                  key={idx}
                  onClick={() => {
                    setQuery(q);
                    handleAsk(q);
                  }}
                  style={{
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: "9999px",
                    padding: "0.35rem 0.75rem",
                    fontSize: "0.78rem",
                    color: "#334155",
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.borderColor = "#059669")}
                  onMouseLeave={(e) => (e.currentTarget.style.borderColor = "#e2e8f0")}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Error Alert */}
        {error && (
          <div
            style={{
              background: "#fef2f2",
              border: "1px solid #fecaca",
              color: "#b91c1c",
              padding: "1rem",
              borderRadius: "10px",
              marginBottom: "1.5rem",
              display: "flex",
              alignItems: "center",
              gap: "0.75rem",
            }}
          >
            <AlertTriangle size={20} />
            <div>{error}</div>
          </div>
        )}

        {/* Result Card */}
        {result && (
          <div
            className="glass-panel animate-fade-in"
            style={{
              background: "#ffffff",
              padding: "2rem",
              borderLeft: "5px solid #059669",
              marginBottom: "2rem",
            }}
          >
            {/* Intent Badge Header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span
                  style={{
                    fontSize: "0.75rem",
                    fontWeight: 700,
                    padding: "0.25rem 0.65rem",
                    borderRadius: "9999px",
                    background: result.intent === "INFORMATIONAL" ? "#ecfdf5" : "#fff7ed",
                    color: result.intent === "INFORMATIONAL" ? "#047857" : "#c2410c",
                    border: `1px solid ${result.intent === "INFORMATIONAL" ? "#a7f3d0" : "#fed7aa"}`,
                  }}
                >
                  INTENT: {result.intent}
                </span>
                <span style={{ fontSize: "0.75rem", color: "#64748b" }}>
                  Active Version Vector Grounding
                </span>
              </div>

              {result.ai_run_id && (
                <button
                  onClick={() => setActiveRunId(result.ai_run_id!)}
                  style={{
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    padding: "0.3rem 0.65rem",
                    borderRadius: "6px",
                    fontSize: "0.75rem",
                    color: "#475569",
                    cursor: "pointer",
                    display: "flex",
                    alignItems: "center",
                    gap: "0.3rem",
                  }}
                >
                  <ShieldCheck size={14} color="#059669" />
                  <span>Verify Execution Trace</span>
                </button>
              )}
            </div>

            {/* Answer Content */}
            <div
              style={{
                fontSize: "1rem",
                lineHeight: 1.7,
                color: "#1e293b",
                marginBottom: "1.5rem",
                whiteSpace: "pre-wrap",
              }}
            >
              {result.answer}
            </div>

            {/* Citations Tray */}
            {result.citations && result.citations.length > 0 && (
              <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", padding: "1rem", borderRadius: "8px", marginBottom: "1.5rem" }}>
                <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "#064e3b", marginBottom: "0.5rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                  <FileText size={16} />
                  Verified Citations ({result.citations.length}):
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
                  {result.citations.map((cit, idx) => (
                    <button
                      key={idx}
                      onClick={() => setSelectedCitation(cit)}
                      style={{
                        background: "#ffffff",
                        border: "1px solid #cbd5e1",
                        borderRadius: "6px",
                        padding: "0.35rem 0.75rem",
                        fontSize: "0.8rem",
                        color: "#047857",
                        fontWeight: 600,
                        cursor: "pointer",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "0.3rem",
                        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                      }}
                    >
                      <span>Doc: {cit.document_title}</span>
                      {cit.chunk_id && (
                        <span style={{ fontSize: "0.7rem", color: "#64748b" }}>#{cit.chunk_id.slice(0, 8)}</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Extracted Facts Tray */}
            {result.extracted_facts && result.extracted_facts.length > 0 && (
              <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "1rem", borderRadius: "8px", marginBottom: "1.5rem" }}>
                <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "#166534", marginBottom: "0.5rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
                  <Car size={16} />
                  Extracted Vehicle & Identity Facts ({result.extracted_facts.length}):
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "0.6rem" }}>
                  {result.extracted_facts.map((fact, idx) => (
                    <div
                      key={idx}
                      style={{
                        background: "#ffffff",
                        border: "1px solid #86efac",
                        padding: "0.4rem 0.6rem",
                        borderRadius: "6px",
                        fontSize: "0.8rem",
                      }}
                    >
                      <div style={{ fontSize: "0.7rem", color: "#64748b", textTransform: "uppercase" }}>{fact.fact_key}</div>
                      <div style={{ fontWeight: 700, color: "#0f172a" }}>{fact.fact_value}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Escalation to Case Banner */}
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "1rem",
                padding: "1.25rem",
                borderRadius: "10px",
                background: result.prompt_case_creation ? "#eff6ff" : "#f8fafc",
                border: `1px solid ${result.prompt_case_creation ? "#bfdbfe" : "#e2e8f0"}`,
              }}
            >
              <div>
                <div style={{ fontWeight: 700, fontSize: "0.95rem", color: "#0f172a" }}>
                  {result.prompt_case_creation ? "Official Case Required" : "Need Direct Officer Assistance?"}
                </div>
                <div style={{ fontSize: "0.8rem", color: "#64748b" }}>
                  {result.prompt_case_creation
                    ? "Your inquiry involves specific vehicle records requiring officer review. Pre-populate a case with these extracted facts."
                    : "You can turn this inquiry into a tracked case without repeating any vehicle details."}
                </div>
              </div>

              <button onClick={handleEscalateToCase} className="btn-primary">
                <span>Open Official Case With These Facts</span>
                <ArrowRight size={16} />
              </button>
            </div>
          </div>
        )}

        {/* Modals */}
        <CitationModal citation={selectedCitation} onClose={() => setSelectedCitation(null)} />
        <AIRunModal runId={activeRunId} onClose={() => setActiveRunId(null)} />
      </div>
    </div>
  );
}
