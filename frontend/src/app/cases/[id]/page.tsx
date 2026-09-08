"use client";

import React, { useEffect, useState, use } from "react";
import Link from "next/link";
import {
  ShieldCheck,
  Clock,
  Car,
  AlertTriangle,
  CheckCircle2,
  Send,
  Upload,
  ArrowLeft,
  FileText,
  MessageSquare,
  RefreshCw,
  User,
  Paperclip,
} from "lucide-react";
import { api } from "@/lib/api";
import { CustomerCaseDetailResponse } from "@/lib/types";
import { formatDate, formatRelativeTime, getPriorityBadge, getStatusBadge } from "@/lib/utils";

const STEPS = ["OPEN", "TRIAGED", "IN_REVIEW", "WAITING", "RESOLVED", "CLOSED"];

export default function CaseDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const caseId = resolvedParams.id;

  const [caseDetail, setCaseDetail] = useState<CustomerCaseDetailResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState<boolean>(false);

  // Reply / Action submission state
  const [replyText, setReplyText] = useState("");
  const [submittingReply, setSubmittingReply] = useState(false);
  const [replySuccess, setReplySuccess] = useState<string | null>(null);

  const fetchCase = async (isManualRefresh: boolean = false) => {
    if (isManualRefresh) setRefreshing(true);
    setError(null);
    try {
      const data = await api.getCase(caseId);
      setCaseDetail(data);
    } catch (err: any) {
      setError(err.message || "Failed to load case timeline.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchCase();
  }, [caseId]);

  const handleSendReply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!replyText.trim()) return;

    setSubmittingReply(true);
    setReplySuccess(null);
    setError(null);

    try {
      const resp = await api.replyToCase(caseId, {
        content: replyText.trim(),
      });
      setReplyText("");
      if (resp.status_shifted_to_in_review) {
        setReplySuccess("Your submission was received. Case status has been automatically moved back to IN_REVIEW.");
      } else {
        setReplySuccess("Message sent to the assigned officer.");
      }
      await fetchCase();
    } catch (err: any) {
      setError(err.message || "Failed to submit customer response.");
    } finally {
      setSubmittingReply(false);
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: "6rem 0", color: "#64748b" }}>
        <RefreshCw className="animate-spin" size={32} style={{ margin: "0 auto 1rem", color: "#059669" }} />
        <div>Loading official case timeline...</div>
      </div>
    );
  }

  if (error && !caseDetail) {
    return (
      <div className="portal-container" style={{ maxWidth: "600px", padding: "4rem 0" }}>
        <div style={{ background: "#fef2f2", border: "1px solid #fecaca", padding: "2rem", borderRadius: "12px", textAlign: "center" }}>
          <AlertTriangle size={36} color="#dc2626" style={{ margin: "0 auto 1rem" }} />
          <h2 style={{ fontSize: "1.25rem", color: "#991b1b", marginBottom: "0.5rem" }}>Unable to Load Case</h2>
          <p style={{ color: "#7f1d1d", fontSize: "0.9rem", marginBottom: "1.5rem" }}>{error}</p>
          <Link href="/track" className="btn-secondary">
            <ArrowLeft size={16} />
            <span>Return to Case Search</span>
          </Link>
        </div>
      </div>
    );
  }

  if (!caseDetail) return null;

  const statusBadge = getStatusBadge(caseDetail.status);
  const priorityBadge = getPriorityBadge(caseDetail.priority);
  const currentStepIdx = STEPS.indexOf(caseDetail.status);

  return (
    <div style={{ padding: "2.5rem 0 5rem" }}>
      <div className="portal-container" style={{ maxWidth: "980px" }}>
        {/* Navigation Breadcrumb & Refresh */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
          <Link
            href="/track"
            style={{ display: "flex", alignItems: "center", gap: "0.4rem", color: "#059669", fontSize: "0.85rem", fontWeight: 600 }}
          >
            <ArrowLeft size={16} />
            <span>Back to Case Search</span>
          </Link>

          <button
            onClick={() => fetchCase(true)}
            disabled={refreshing}
            style={{
              background: "#ffffff",
              border: "1px solid #cbd5e1",
              borderRadius: "8px",
              padding: "0.4rem 0.85rem",
              fontSize: "0.8rem",
              fontWeight: 600,
              color: "#334155",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
            }}
          >
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
            <span>{refreshing ? "Refreshing..." : "Refresh Status"}</span>
          </button>
        </div>

        {/* Case Header Card */}
        <div className="glass-panel" style={{ padding: "2rem", background: "#ffffff", marginBottom: "1.75rem" }}>
          <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "flex-start", gap: "1rem", marginBottom: "1.25rem" }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.4rem" }}>
                <span style={{ fontSize: "1.35rem", fontWeight: 800, color: "#064e3b", letterSpacing: "0.02em" }}>
                  {caseDetail.case_number}
                </span>
                <span
                  className="badge"
                  style={{ background: statusBadge.bg, color: statusBadge.text, borderColor: statusBadge.border }}
                >
                  {statusBadge.label}
                </span>
                <span
                  className="badge"
                  style={{ background: priorityBadge.bg, color: priorityBadge.text, borderColor: priorityBadge.border }}
                >
                  Priority: {priorityBadge.label}
                </span>
              </div>
              <h1 style={{ fontSize: "1.25rem", fontWeight: 700, color: "#0f172a" }}>
                {caseDetail.subject}
              </h1>
              <div style={{ fontSize: "0.8rem", color: "#64748b", marginTop: "0.25rem" }}>
                Category: <strong>{caseDetail.category}</strong> • Opened on {formatDate(caseDetail.created_at)}
              </div>
            </div>

            {/* SLA Badge */}
            {caseDetail.sla_deadline && (
              <div
                style={{
                  background: "#f8fafc",
                  border: "1px solid #e2e8f0",
                  padding: "0.6rem 1rem",
                  borderRadius: "8px",
                  textAlign: "right",
                }}
              >
                <div style={{ fontSize: "0.7rem", color: "#64748b", fontWeight: 700, textTransform: "uppercase", display: "flex", alignItems: "center", justifyContent: "flex-end", gap: "0.3rem" }}>
                  <Clock size={12} color="#059669" />
                  SLA RESOLUTION TARGET
                </div>
                <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#0f172a" }}>
                  {formatDate(caseDetail.sla_deadline)}
                </div>
              </div>
            )}
          </div>

          {/* Stepper */}
          <div className="stepper-container" style={{ margin: "2rem 0 1rem" }}>
            <div className="stepper-line" />
            <div
              className="stepper-line-progress"
              style={{
                width: currentStepIdx >= 0 ? `${(currentStepIdx / (STEPS.length - 1)) * 100}%` : "0%",
              }}
            />

            {STEPS.map((s, idx) => {
              const isCompleted = currentStepIdx > idx;
              const isActive = caseDetail.status === s;
              return (
                <div key={s} className={`step-node ${isActive ? "active" : ""} ${isCompleted ? "completed" : ""}`}>
                  <div className="step-circle">
                    {isCompleted ? <CheckCircle2 size={18} /> : idx + 1}
                  </div>
                  <div className="step-label">{s}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* PROMINENT "ACTION REQUIRED" BANNER (WHEN STATUS == WAITING) */}
        {caseDetail.status === "WAITING" && (
          <div
            className="glass-panel animate-fade-in"
            style={{
              padding: "1.75rem",
              background: "#fffbeb",
              border: "2px solid #f59e0b",
              borderRadius: "12px",
              marginBottom: "1.75rem",
            }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", gap: "0.75rem", marginBottom: "1rem" }}>
              <div
                style={{
                  width: "40px",
                  height: "40px",
                  borderRadius: "8px",
                  background: "#fef3c7",
                  color: "#b45309",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                }}
              >
                <AlertTriangle size={24} />
              </div>
              <div>
                <h3 style={{ fontSize: "1.1rem", fontWeight: 800, color: "#92400e", marginBottom: "0.25rem" }}>
                  Action Required From You
                </h3>
                <p style={{ color: "#78350f", fontSize: "0.9rem", lineHeight: 1.5 }}>
                  The assigned CMR officer has paused review and requested additional clarification or supporting documentation:
                </p>
                {caseDetail.requested_actions.map((ra, idx) => (
                  <div
                    key={idx}
                    style={{
                      background: "#ffffff",
                      border: "1px solid #fde68a",
                      padding: "0.75rem 1rem",
                      borderRadius: "8px",
                      marginTop: "0.5rem",
                      fontWeight: 600,
                      color: "#92400e",
                      fontSize: "0.88rem",
                    }}
                  >
                    &ldquo;{ra.reason || "Please provide the requested documents to continue processing."}&rdquo;
                  </div>
                ))}
              </div>
            </div>

            <div style={{ fontSize: "0.8rem", color: "#92400e", fontWeight: 600, marginTop: "0.5rem" }}>
              ⬇️ Submit your response or upload below. Submitting will automatically shift the case back to <strong>IN_REVIEW</strong>.
            </div>
          </div>
        )}

        {/* Layout: Main Feed & Sidebar */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: "1.75rem" }}>
          {/* LEFT COLUMN: Timeline & Messages */}
          <div style={{ display: "flex", flexDirection: "column", gap: "1.75rem" }}>
            {/* Conversation & Action Feed */}
            <div className="glass-panel" style={{ padding: "1.75rem", background: "#ffffff" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1.25rem" }}>
                <MessageSquare size={18} color="#059669" />
                <h3 style={{ fontSize: "1rem", fontWeight: 700, color: "#0f172a" }}>
                  Case Communications & Public Notes
                </h3>
              </div>

              {caseDetail.messages.length === 0 ? (
                <div style={{ textAlign: "center", padding: "2rem", color: "#94a3b8", fontSize: "0.85rem" }}>
                  No messages yet. Use the reply box below to communicate with the assigned officer.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "1rem", marginBottom: "1.5rem" }}>
                  {caseDetail.messages.map((msg) => {
                    const isCustomer = msg.sender_type === "customer";
                    return (
                      <div
                        key={msg.id}
                        style={{
                          alignSelf: isCustomer ? "flex-end" : "flex-start",
                          maxWidth: "85%",
                          background: isCustomer ? "#ecfdf5" : "#f8fafc",
                          border: `1px solid ${isCustomer ? "#a7f3d0" : "#e2e8f0"}`,
                          borderRadius: "10px",
                          padding: "0.85rem 1rem",
                        }}
                      >
                        <div style={{ display: "flex", justifyContent: "space-between", gap: "1rem", marginBottom: "0.3rem", fontSize: "0.72rem", color: "#64748b" }}>
                          <span style={{ fontWeight: 700, color: isCustomer ? "#047857" : "#0284c7" }}>
                            {isCustomer ? "You (Customer)" : "CMR Support Officer"}
                          </span>
                          <span>{formatRelativeTime(msg.created_at)}</span>
                        </div>
                        <div style={{ fontSize: "0.9rem", color: "#1e293b", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                          {msg.content}
                        </div>

                        {msg.attachments && msg.attachments.length > 0 && (
                          <div style={{ marginTop: "0.5rem", borderTop: "1px solid rgba(0,0,0,0.06)", paddingTop: "0.5rem" }}>
                            {msg.attachments.map((att: any, idx: number) => (
                              <div key={idx} style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: "0.75rem", color: "#059669" }}>
                                <Paperclip size={12} />
                                <span>{att.filename || "Attachment"}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Reply Box */}
              <form onSubmit={handleSendReply} style={{ borderTop: "1px solid #f1f5f9", paddingTop: "1.25rem" }}>
                {replySuccess && (
                  <div style={{ background: "#ecfdf5", color: "#047857", padding: "0.6rem 0.85rem", borderRadius: "6px", fontSize: "0.82rem", marginBottom: "0.75rem" }}>
                    {replySuccess}
                  </div>
                )}
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <textarea
                    rows={2}
                    value={replyText}
                    onChange={(e) => setReplyText(e.target.value)}
                    placeholder={caseDetail.status === "WAITING" ? "Enter the requested information or confirm document upload..." : "Type your message to the assigned officer..."}
                    style={{
                      flex: 1,
                      padding: "0.75rem",
                      borderRadius: "8px",
                      border: "1px solid #cbd5e1",
                      fontSize: "0.9rem",
                      resize: "none",
                      fontFamily: "inherit",
                    }}
                  />
                  <button
                    type="submit"
                    disabled={submittingReply || !replyText.trim()}
                    className="btn-primary"
                    style={{ padding: "0 1.25rem", height: "auto" }}
                  >
                    <Send size={16} />
                  </button>
                </div>
              </form>
            </div>

            {/* Chronological State Machine Activity Timeline */}
            <div className="glass-panel" style={{ padding: "1.75rem", background: "#ffffff" }}>
              <h3 style={{ fontSize: "1rem", fontWeight: 700, color: "#0f172a", marginBottom: "1.25rem" }}>
                Official Event & Milestone Log
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "1rem", position: "relative", paddingLeft: "1.5rem" }}>
                {/* Vertical timeline line */}
                <div style={{ position: "absolute", left: "6px", top: "10px", bottom: "10px", width: "2px", background: "#e2e8f0" }} />

                {caseDetail.timeline.map((item, idx) => (
                  <div key={idx} style={{ position: "relative" }}>
                    <div
                      style={{
                        position: "absolute",
                        left: "-1.5rem",
                        top: "4px",
                        width: "14px",
                        height: "14px",
                        borderRadius: "50%",
                        background: "#059669",
                        border: "2px solid #ffffff",
                        boxShadow: "0 0 0 2px #a7f3d0",
                      }}
                    />
                    <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#0f172a" }}>
                      {item.description}
                    </div>
                    <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
                      Actor: {item.actor_role} • {formatDate(item.timestamp)}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* RIGHT COLUMN: Extracted Facts & Details */}
          <div style={{ display: "flex", flexDirection: "column", gap: "1.75rem" }}>
            {/* Extracted Vehicle Facts */}
            <div className="glass-panel" style={{ padding: "1.5rem", background: "#ffffff" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "1rem" }}>
                <Car size={18} color="#064e3b" />
                <h3 style={{ fontSize: "0.95rem", fontWeight: 700, color: "#0f172a" }}>
                  Vehicle Facts Record
                </h3>
              </div>

              {caseDetail.extracted_facts.length === 0 ? (
                <div style={{ fontSize: "0.8rem", color: "#94a3b8" }}>
                  No vehicle facts registered on this case.
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
                  {caseDetail.extracted_facts.map((fact, idx) => (
                    <div
                      key={idx}
                      style={{
                        background: "#f8fafc",
                        border: "1px solid #e2e8f0",
                        padding: "0.5rem 0.75rem",
                        borderRadius: "6px",
                      }}
                    >
                      <div style={{ fontSize: "0.7rem", color: "#64748b", textTransform: "uppercase" }}>{fact.fact_key}</div>
                      <div style={{ fontWeight: 700, fontSize: "0.88rem", color: "#0f172a" }}>{fact.fact_value}</div>
                      <div style={{ fontSize: "0.68rem", color: fact.verified ? "#15803d" : "#b45309" }}>
                        {fact.verified ? "✓ Verified Fact" : "Unverified (Customer provided)"}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Case Details Card */}
            <div className="glass-panel" style={{ padding: "1.5rem", background: "#ffffff" }}>
              <h3 style={{ fontSize: "0.95rem", fontWeight: 700, color: "#0f172a", marginBottom: "1rem" }}>
                Case Identification
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", fontSize: "0.8rem" }}>
                <div>
                  <div style={{ color: "#64748b" }}>Case UUID</div>
                  <code style={{ fontSize: "0.72rem", color: "#0f172a", wordBreak: "break-all" }}>{caseDetail.id}</code>
                </div>
                <div>
                  <div style={{ color: "#64748b" }}>Last Updated</div>
                  <div style={{ fontWeight: 600, color: "#0f172a" }}>{formatDate(caseDetail.updated_at)}</div>
                </div>
                <div>
                  <div style={{ color: "#64748b" }}>Category</div>
                  <div style={{ fontWeight: 600, color: "#059669" }}>{caseDetail.category}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
