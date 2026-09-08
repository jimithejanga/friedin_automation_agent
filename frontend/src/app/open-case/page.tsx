"use client";

import React, { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  Car,
  User,
  Upload,
  CheckCircle2,
  ArrowRight,
  ArrowLeft,
  AlertCircle,
  FileText,
  Trash2,
  ShieldCheck,
  Search,
} from "lucide-react";
import { api } from "@/lib/api";
import { CasePriority, CustomerCaseResponse, ExtractedFactSchema } from "@/lib/types";

const CATEGORIES = [
  { value: "GENERAL_INQUIRY", label: "General CMR Inquiry" },
  { value: "CHANGE_OF_OWNERSHIP", label: "Change of Vehicle Ownership" },
  { value: "TINTED_PERMIT", label: "Tinted Glass Permit Application" },
  { value: "PLATE_VERIFICATION", label: "Number Plate Verification / Issuance" },
  { value: "ENGINE_SWAP", label: "Engine Replacement / Chassis Clearance" },
  { value: "VEHICLE_LICENSE", label: "Vehicle License Renewal" },
];

function CaseWizardContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [currentStep, setCurrentStep] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [createdCase, setCreatedCase] = useState<CustomerCaseResponse | null>(null);

  // Form State
  const [subject, setSubject] = useState("");
  const [category, setCategory] = useState("GENERAL_INQUIRY");
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<CasePriority>("NORMAL");
  const [conversationId, setConversationId] = useState<string | null>(null);

  // Vehicle facts
  const [plateNumber, setPlateNumber] = useState("");
  const [vinNumber, setVinNumber] = useState("");
  const [engineNumber, setEngineNumber] = useState("");
  const [stateOfReg, setStateOfReg] = useState("Lagos");

  // Contact State
  const [fullName, setFullName] = useState("");
  const [phoneNumber, setPhoneNumber] = useState("");
  const [email, setEmail] = useState("");
  const [ninOrBvn, setNinOrBvn] = useState("");

  // Attachments State
  const [files, setFiles] = useState<Array<{ name: string; size: string; type: string }>>([]);

  // Prepopulate from URL search params
  useEffect(() => {
    const convId = searchParams.get("conversation_id");
    const subj = searchParams.get("subject");
    const cat = searchParams.get("category");
    const name = searchParams.get("full_name");
    const phone = searchParams.get("phone_number");

    if (convId) setConversationId(convId);
    if (subj) setSubject(subj);
    if (cat) setCategory(cat);
    if (name) setFullName(name);
    if (phone) setPhoneNumber(phone);

    // Check for vehicle facts in query params
    const plate = searchParams.get("fact_plate_number") || searchParams.get("fact_plate");
    const vin = searchParams.get("fact_vin") || searchParams.get("fact_chassis");
    const state = searchParams.get("fact_state");

    if (plate) setPlateNumber(plate);
    if (vin) setVinNumber(vin);
    if (state) setStateOfReg(state);
  }, [searchParams]);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files) return;
    const newFiles = Array.from(e.target.files).map((f) => ({
      name: f.name,
      size: (f.size / 1024).toFixed(1) + " KB",
      type: f.type || "application/pdf",
    }));
    setFiles((prev) => [...prev, ...newFiles]);
  };

  const removeFile = (idx: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const validateStep = (step: number): boolean => {
    setError(null);
    if (step === 1) {
      if (!subject.trim() || subject.length < 3) {
        setError("Subject must be at least 3 characters long.");
        return false;
      }
      return true;
    }
    if (step === 2) {
      if (!phoneNumber.trim()) {
        setError("Customer phone number is required to receive official case SMS notifications.");
        return false;
      }
      return true;
    }
    return true;
  };

  const handleNext = () => {
    if (validateStep(currentStep)) {
      setCurrentStep((prev) => Math.min(prev + 1, 4));
    }
  };

  const handlePrev = () => {
    setError(null);
    setCurrentStep((prev) => Math.max(prev - 1, 1));
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);

    const additionalFacts: ExtractedFactSchema[] = [];
    if (plateNumber.trim()) {
      additionalFacts.push({
        fact_key: "plate_number",
        fact_value: plateNumber.trim().toUpperCase(),
        confidence: 1.0,
        source: "CUSTOMER_INPUT",
        verified: false,
      });
    }
    if (vinNumber.trim()) {
      additionalFacts.push({
        fact_key: "vin",
        fact_value: vinNumber.trim().toUpperCase(),
        confidence: 1.0,
        source: "CUSTOMER_INPUT",
        verified: false,
      });
    }
    if (engineNumber.trim()) {
      additionalFacts.push({
        fact_key: "engine_number",
        fact_value: engineNumber.trim().toUpperCase(),
        confidence: 1.0,
        source: "CUSTOMER_INPUT",
        verified: false,
      });
    }
    if (stateOfReg.trim()) {
      additionalFacts.push({
        fact_key: "state_of_registration",
        fact_value: stateOfReg.trim(),
        confidence: 1.0,
        source: "CUSTOMER_INPUT",
        verified: false,
      });
    }

    try {
      const resp = await api.openCase({
        subject: subject.trim(),
        category,
        description: description.trim() || undefined,
        priority,
        conversation_id: conversationId,
        full_name: fullName.trim() || undefined,
        phone_number: phoneNumber.trim() || undefined,
        email: email.trim() || undefined,
        nin_or_bvn: ninOrBvn.trim() || undefined,
        additional_facts: additionalFacts,
        metadata_json: {
          submitted_via: "web_customer_portal",
          uploaded_documents_count: files.length,
          uploaded_documents: files.map((f) => f.name),
        },
      });

      // Save to recent cases in localStorage
      try {
        const recent = JSON.parse(localStorage.getItem("cmr_recent_cases") || "[]");
        recent.unshift({
          id: resp.id,
          case_number: resp.case_number,
          subject: resp.subject,
          created_at: resp.created_at,
        });
        localStorage.setItem("cmr_recent_cases", JSON.stringify(recent.slice(0, 10)));
      } catch {
        // ignore localStorage error
      }

      setCreatedCase(resp);
    } catch (err: any) {
      setError(err.message || "Failed to create official support case.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: "3rem 0 5rem" }}>
      <div className="portal-container" style={{ maxWidth: "760px" }}>
        {/* Header */}
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <h1 style={{ fontSize: "2rem", fontWeight: 800, color: "#064e3b", letterSpacing: "-0.02em" }}>
            Official Case Intake Wizard
          </h1>
          <p style={{ color: "#475569", fontSize: "0.95rem" }}>
            Open a formal Central Motor Registry case. Every case is assigned an officer and tracked via SLA.
          </p>
        </div>

        {/* Success Confirmation View */}
        {createdCase ? (
          <div
            className="glass-panel animate-fade-in"
            style={{
              padding: "2.5rem",
              background: "#ffffff",
              textAlign: "center",
              borderTop: "6px solid #059669",
            }}
          >
            <div
              style={{
                width: "64px",
                height: "64px",
                borderRadius: "50%",
                background: "#ecfdf5",
                color: "#059669",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                margin: "0 auto 1.25rem",
              }}
            >
              <CheckCircle2 size={36} />
            </div>

            <h2 style={{ fontSize: "1.5rem", fontWeight: 800, color: "#0f172a", marginBottom: "0.5rem" }}>
              Case Successfully Registered
            </h2>
            <p style={{ color: "#64748b", fontSize: "0.9rem", marginBottom: "1.75rem" }}>
              Your case has been logged into the CMR dispatch queue with state <strong>OPEN</strong>.
            </p>

            <div
              style={{
                background: "#f8fafc",
                border: "2px dashed #cbd5e1",
                padding: "1.5rem",
                borderRadius: "12px",
                marginBottom: "2rem",
                display: "inline-block",
                minWidth: "320px",
              }}
            >
              <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#64748b", textTransform: "uppercase" }}>
                YOUR OFFICIAL CASE NUMBER
              </div>
              <div style={{ fontSize: "1.75rem", fontWeight: 800, color: "#064e3b", letterSpacing: "0.05em", margin: "0.4rem 0" }}>
                {createdCase.case_number}
              </div>
              <div style={{ fontSize: "0.8rem", color: "#059669", fontWeight: 600 }}>
                Please save this number for SMS & web tracking
              </div>
            </div>

            <div style={{ display: "flex", justifyContent: "center", gap: "1rem" }}>
              <Link href={`/cases/${createdCase.id}`} className="btn-primary" style={{ padding: "0.75rem 2rem" }}>
                <span>Track Case Timeline Now</span>
                <ArrowRight size={16} />
              </Link>
              <Link href="/" className="btn-secondary" style={{ padding: "0.75rem 1.5rem" }}>
                Return Home
              </Link>
            </div>
          </div>
        ) : (
          /* Multi-Step Wizard */
          <div className="glass-panel" style={{ padding: "2rem", background: "#ffffff" }}>
            {/* Stepper Header */}
            <div className="stepper-container">
              <div className="stepper-line" />
              <div
                className="stepper-line-progress"
                style={{ width: `${((currentStep - 1) / 3) * 100}%` }}
              />

              {[
                { step: 1, label: "Vehicle & Issue", icon: Car },
                { step: 2, label: "Identity", icon: User },
                { step: 3, label: "Documents", icon: Upload },
                { step: 4, label: "Confirmation", icon: ShieldCheck },
              ].map((s) => {
                const isCompleted = currentStep > s.step;
                const isActive = currentStep === s.step;
                return (
                  <div
                    key={s.step}
                    className={`step-node ${isActive ? "active" : ""} ${isCompleted ? "completed" : ""}`}
                  >
                    <div className="step-circle">
                      {isCompleted ? <CheckCircle2 size={18} /> : s.step}
                    </div>
                    <div className="step-label">{s.label}</div>
                  </div>
                );
              })}
            </div>

            {/* Error Message */}
            {error && (
              <div
                style={{
                  background: "#fef2f2",
                  border: "1px solid #fecaca",
                  color: "#b91c1c",
                  padding: "0.85rem 1rem",
                  borderRadius: "8px",
                  marginBottom: "1.5rem",
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

            {/* STEP 1: VEHICLE & ISSUE */}
            {currentStep === 1 && (
              <div className="animate-fade-in" style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                <h3 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#0f172a" }}>
                  1. Vehicle & Issue Details
                </h3>

                <div>
                  <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                    Subject / Summary <span style={{ color: "#ef4444" }}>*</span>
                  </label>
                  <input
                    type="text"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    placeholder="e.g. Request for Tinted Glass Clearance Certificate"
                    style={{
                      width: "100%",
                      padding: "0.75rem",
                      borderRadius: "8px",
                      border: "1px solid #cbd5e1",
                      fontSize: "0.95rem",
                    }}
                  />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                  <div>
                    <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                      Category
                    </label>
                    <select
                      value={category}
                      onChange={(e) => setCategory(e.target.value)}
                      style={{
                        width: "100%",
                        padding: "0.75rem",
                        borderRadius: "8px",
                        border: "1px solid #cbd5e1",
                        fontSize: "0.9rem",
                        background: "#ffffff",
                      }}
                    >
                      {CATEGORIES.map((cat) => (
                        <option key={cat.value} value={cat.value}>
                          {cat.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                      Priority
                    </label>
                    <select
                      value={priority}
                      onChange={(e) => setPriority(e.target.value as CasePriority)}
                      style={{
                        width: "100%",
                        padding: "0.75rem",
                        borderRadius: "8px",
                        border: "1px solid #cbd5e1",
                        fontSize: "0.9rem",
                        background: "#ffffff",
                      }}
                    >
                      <option value="LOW">Low</option>
                      <option value="NORMAL">Normal (Standard SLA)</option>
                      <option value="HIGH">High</option>
                      <option value="URGENT">Urgent (Immediate)</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                    Detailed Problem Description
                  </label>
                  <textarea
                    rows={4}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Provide relevant details regarding the vehicle, previous license, or specific assistance required..."
                    style={{
                      width: "100%",
                      padding: "0.75rem",
                      borderRadius: "8px",
                      border: "1px solid #cbd5e1",
                      fontSize: "0.9rem",
                      lineHeight: 1.5,
                      fontFamily: "inherit",
                    }}
                  />
                </div>

                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", padding: "1rem", borderRadius: "8px" }}>
                  <div style={{ fontSize: "0.85rem", fontWeight: 700, color: "#064e3b", marginBottom: "0.75rem" }}>
                    Vehicle Facts (Optional but speeds up resolution):
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
                    <div>
                      <label style={{ fontSize: "0.75rem", color: "#64748b", display: "block", marginBottom: "0.2rem" }}>
                        Plate Number
                      </label>
                      <input
                        type="text"
                        value={plateNumber}
                        onChange={(e) => setPlateNumber(e.target.value)}
                        placeholder="e.g. KJA-821-XA"
                        style={{ width: "100%", padding: "0.5rem", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: "0.75rem", color: "#64748b", display: "block", marginBottom: "0.2rem" }}>
                        VIN / Chassis Number
                      </label>
                      <input
                        type="text"
                        value={vinNumber}
                        onChange={(e) => setVinNumber(e.target.value)}
                        placeholder="17-char VIN"
                        style={{ width: "100%", padding: "0.5rem", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: "0.75rem", color: "#64748b", display: "block", marginBottom: "0.2rem" }}>
                        State of Registration
                      </label>
                      <input
                        type="text"
                        value={stateOfReg}
                        onChange={(e) => setStateOfReg(e.target.value)}
                        placeholder="e.g. Lagos"
                        style={{ width: "100%", padding: "0.5rem", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
                      />
                    </div>
                    <div>
                      <label style={{ fontSize: "0.75rem", color: "#64748b", display: "block", marginBottom: "0.2rem" }}>
                        Engine Number
                      </label>
                      <input
                        type="text"
                        value={engineNumber}
                        onChange={(e) => setEngineNumber(e.target.value)}
                        placeholder="e.g. 2AZ-FE-987"
                        style={{ width: "100%", padding: "0.5rem", borderRadius: "6px", border: "1px solid #cbd5e1", fontSize: "0.85rem" }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* STEP 2: APPLICANT IDENTITY */}
            {currentStep === 2 && (
              <div className="animate-fade-in" style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                <h3 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#0f172a" }}>
                  2. Applicant Contact & Identity
                </h3>
                <p style={{ fontSize: "0.85rem", color: "#64748b" }}>
                  Official notifications and officer communications will be linked to this identity.
                </p>

                <div>
                  <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                    Full Legal Name
                  </label>
                  <input
                    type="text"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="e.g. Babatunde Adeyemi"
                    style={{ width: "100%", padding: "0.75rem", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "0.95rem" }}
                  />
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
                  <div>
                    <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                      Phone Number <span style={{ color: "#ef4444" }}>*</span>
                    </label>
                    <input
                      type="tel"
                      value={phoneNumber}
                      onChange={(e) => setPhoneNumber(e.target.value)}
                      placeholder="+2348012345678"
                      style={{ width: "100%", padding: "0.75rem", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "0.95rem" }}
                    />
                  </div>

                  <div>
                    <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                      Email Address
                    </label>
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="e.g. b.adeyemi@gmail.com"
                      style={{ width: "100%", padding: "0.75rem", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "0.95rem" }}
                    />
                  </div>
                </div>

                <div>
                  <label style={{ display: "block", fontSize: "0.85rem", fontWeight: 600, color: "#334155", marginBottom: "0.35rem" }}>
                    NIN or BVN (Optional Verification)
                  </label>
                  <input
                    type="text"
                    value={ninOrBvn}
                    onChange={(e) => setNinOrBvn(e.target.value)}
                    placeholder="11-digit NIN or BVN for instant verification"
                    style={{ width: "100%", padding: "0.75rem", borderRadius: "8px", border: "1px solid #cbd5e1", fontSize: "0.95rem" }}
                  />
                </div>
              </div>
            )}

            {/* STEP 3: DOCUMENT UPLOAD */}
            {currentStep === 3 && (
              <div className="animate-fade-in" style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                <h3 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#0f172a" }}>
                  3. Supporting Documents & Proofs
                </h3>
                <p style={{ fontSize: "0.85rem", color: "#64748b" }}>
                  Upload clear photos or scans of your vehicle license, proof of purchase, or inspection report.
                </p>

                {/* Dropzone */}
                <label
                  style={{
                    border: "2px dashed #059669",
                    background: "#f0fdf4",
                    borderRadius: "12px",
                    padding: "2.5rem 1.5rem",
                    textAlign: "center",
                    cursor: "pointer",
                    display: "block",
                    transition: "all 0.2s ease",
                  }}
                >
                  <input
                    type="file"
                    multiple
                    accept=".pdf,.png,.jpg,.jpeg"
                    onChange={handleFileUpload}
                    style={{ display: "none" }}
                  />
                  <div
                    style={{
                      width: "48px",
                      height: "48px",
                      borderRadius: "50%",
                      background: "#ffffff",
                      color: "#059669",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      margin: "0 auto 0.75rem",
                      boxShadow: "0 2px 6px rgba(0,0,0,0.06)",
                    }}
                  >
                    <Upload size={24} />
                  </div>
                  <div style={{ fontWeight: 700, color: "#064e3b", fontSize: "1rem", marginBottom: "0.25rem" }}>
                    Click to browse or drop documents here
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "#64748b" }}>
                    PDF, JPEG, or PNG files up to 10MB each
                  </div>
                </label>

                {/* Uploaded Files List */}
                {files.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                    <div style={{ fontSize: "0.8rem", fontWeight: 600, color: "#475569" }}>
                      Selected Documents ({files.length}):
                    </div>
                    {files.map((file, idx) => (
                      <div
                        key={idx}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "space-between",
                          background: "#f8fafc",
                          border: "1px solid #e2e8f0",
                          padding: "0.6rem 0.85rem",
                          borderRadius: "6px",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                          <FileText size={18} color="#059669" />
                          <div>
                            <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "#0f172a" }}>{file.name}</div>
                            <div style={{ fontSize: "0.7rem", color: "#94a3b8" }}>{file.size}</div>
                          </div>
                        </div>
                        <button
                          onClick={() => removeFile(idx)}
                          style={{ background: "transparent", border: "none", color: "#ef4444", cursor: "pointer" }}
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* STEP 4: CONFIRMATION & REVIEW */}
            {currentStep === 4 && (
              <div className="animate-fade-in" style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
                <h3 style={{ fontSize: "1.15rem", fontWeight: 700, color: "#0f172a" }}>
                  4. Review & Confirm Submission
                </h3>

                <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", padding: "1.25rem", borderRadius: "10px" }}>
                  <div style={{ marginBottom: "1rem" }}>
                    <div style={{ fontSize: "0.75rem", color: "#64748b", textTransform: "uppercase" }}>ISSUE TITLE</div>
                    <div style={{ fontWeight: 700, fontSize: "1.05rem", color: "#0f172a" }}>{subject}</div>
                    <div style={{ fontSize: "0.8rem", color: "#059669", fontWeight: 600 }}>Category: {category}</div>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", borderTop: "1px solid #e2e8f0", paddingTop: "0.75rem", marginBottom: "1rem" }}>
                    <div>
                      <div style={{ fontSize: "0.75rem", color: "#64748b" }}>APPLICANT</div>
                      <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>{fullName || "N/A"}</div>
                      <div style={{ fontSize: "0.8rem", color: "#475569" }}>{phoneNumber}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: "0.75rem", color: "#64748b" }}>VEHICLE RECORD</div>
                      <div style={{ fontWeight: 600, fontSize: "0.9rem" }}>Plate: {plateNumber || "Not provided"}</div>
                      <div style={{ fontSize: "0.8rem", color: "#475569" }}>VIN: {vinNumber || "Not provided"}</div>
                    </div>
                  </div>

                  {files.length > 0 && (
                    <div style={{ borderTop: "1px solid #e2e8f0", paddingTop: "0.75rem" }}>
                      <div style={{ fontSize: "0.75rem", color: "#64748b" }}>ATTACHMENTS ({files.length})</div>
                      <div style={{ fontSize: "0.8rem", color: "#059669" }}>{files.map((f) => f.name).join(", ")}</div>
                    </div>
                  )}
                </div>

                <div style={{ background: "#f0fdf4", border: "1px solid #bbf7d0", padding: "0.85rem", borderRadius: "8px", fontSize: "0.8rem", color: "#166534" }}>
                  By clicking Submit, your case will be registered in the official Central Motor Registry triage system. An automated SLA deadline will be assigned.
                </div>
              </div>
            )}

            {/* Navigation Buttons */}
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: "2rem", borderTop: "1px solid #f1f5f9", paddingTop: "1.25rem" }}>
              {currentStep > 1 ? (
                <button onClick={handlePrev} className="btn-secondary">
                  <ArrowLeft size={16} />
                  <span>Back</span>
                </button>
              ) : (
                <div />
              )}

              {currentStep < 4 ? (
                <button onClick={handleNext} className="btn-primary">
                  <span>Continue</span>
                  <ArrowRight size={16} />
                </button>
              ) : (
                <button onClick={handleSubmit} disabled={loading} className="btn-primary" style={{ padding: "0.75rem 2rem" }}>
                  {loading ? "Registering Case..." : "Submit Official Case"}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function OpenCasePage() {
  return (
    <Suspense fallback={<div style={{ textAlign: "center", padding: "4rem" }}>Loading Case Intake Wizard...</div>}>
      <CaseWizardContent />
    </Suspense>
  );
}
