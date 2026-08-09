'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import {
  HeartPulse,
  ArrowLeft,
  Building2,
  Sparkles,
  Loader2,
  X,
  FileText,
  ShieldCheck,
  CheckCircle2,
  Database,
  Activity,
  Download,
} from 'lucide-react';
import { Badge } from '@/Components/ui/badge';
import { Button } from '@/Components/ui/button';
import { Progress } from '@/Components/ui/progress';
import LogoutButton from '@/Components/LogoutButton';
import PWAInstallButton from '@/Components/PWAInstallButton';
import {
  getPatients,
  generateClaimDossier,
  downloadClaimPDF,
  getApiErrorMessage,
  type ClaimCode,
  type ClaimDossier as ClaimDossierData,
  type ComplianceMeta,
  type PatientRecord,
} from '@/Services/api';

/**
 * Hospital Admin Command Center — high-density fintech data grid for hospital
 * administrators. Lists patients with IDs, 14-digit ABHA (JetBrains Mono),
 * diagnosis, status, and adherence.
 *
 * Agent 5 integration: each row has a glowing "Generate TPA Insurance Dossier"
 * button that calls `/api/claim/generate` with the patient's ABHA id + consent,
 * then opens an ICD-10 Claim Dossier modal with the ABDM/DPDP data-residency
 * footer.
 */
type Status = PatientRecord['status'];

const STATUS_TONE: Record<Status, 'emerald' | 'blue' | 'rose' | 'slate'> = {
  Stable: 'emerald',
  Monitoring: 'blue',
  Critical: 'rose',
  Discharged: 'slate',
};

export default function AdminPage() {
  const [patients, setPatients] = useState<PatientRecord[]>([]);
  const [source, setSource] = useState<'supabase' | 'unconfigured' | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  // Dossier modal state.
  const [activePatient, setActivePatient] = useState<PatientRecord | null>(null);
  const [generating, setGenerating] = useState(false);
  const [dossier, setDossier] = useState<ClaimDossierData | null>(null);
  const [htmlReport, setHtmlReport] = useState<string | null>(null);
  const [compliance, setCompliance] = useState<ComplianceMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  // True while the server-side /api/claim/pdf render is in flight. Drives the
  // Download PDF button's busy state and disables it (and Close stays enabled).
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    getPatients()
      .then((res) => {
        setPatients(res.patients);
        setSource(res.source);
        setLoading(false);
      })
      .catch((e: unknown) => {
        setFetchError(getApiErrorMessage(e, 'Unable to reach the patient registry.'));
        setLoading(false);
      });
  }, []);

  const openDossier = async (p: PatientRecord) => {
    setActivePatient(p);
    setDossier(null);
    setHtmlReport(null);
    setCompliance(null);
    setError(null);
    setGenerating(true);

    try {
      const patientData = {
        patient_id: p.patient_id,
        extracted: p.extracted,
        safety_flags: p.safety_flags,
        teach_back: { questions_asked: [], patient_responses: [], understanding_score: 0, corrections_given: [] },
      };
      const res = await generateClaimDossier(patientData, 'priyanshucreator3@gmail.com', {
        abhaId: p.abha_id,
        consentGranted: true,
      });
      setDossier(res?.dossier ?? null);
      setHtmlReport(res?.html_report ?? null);
      setCompliance(res?.compliance_metadata ?? null);
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Dossier generation failed.'));
    } finally {
      setGenerating(false);
    }
  };

  const closeDossier = () => {
    setActivePatient(null);
    setDossier(null);
    setHtmlReport(null);
    setCompliance(null);
    setError(null);
  };

  // Download the generated dossier as a server-rendered PDF. Re-uses the SAME
  // patientData shape (and ABHA id + consent) that openDossier sent to
  // /api/claim/generate, so the PDF reflects the dossier the admin is looking
  // at — never a client-supplied payload. Gated on a successfully generated
  // dossier so the button can't fire mid-generation or on an error state.
  const handleDownloadPDF = async () => {
    if (!activePatient || generating || !dossier) return;
    setDownloading(true);
    try {
      const patientData = {
        patient_id: activePatient.patient_id,
        extracted: activePatient.extracted,
        safety_flags: activePatient.safety_flags,
        teach_back: { questions_asked: [], patient_responses: [], understanding_score: 0, corrections_given: [] },
      };
      await downloadClaimPDF(patientData, 'priyanshucreator3@gmail.com', {
        abhaId: activePatient.abha_id,
        consentGranted: true,
      });
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'PDF download failed.'));
    } finally {
      setDownloading(false);
    }
  };

  const icdCodes: ClaimCode[] =
    dossier?.icd_codes || dossier?.icd_10_codes || dossier?.diagnosis_codes || [];

  const billingTotal =
    dossier?.estimated_reimbursement || dossier?.total_estimated_cost || dossier?.billing?.total || dossier?.claim_total;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 antialiased font-sans flex flex-col pb-12">
      {/* Admin Header */}
      <header className="bg-white/80 backdrop-blur-md border-b border-slate-200 sticky top-0 z-50 px-6 py-4 shadow-xs">
        <div className="max-w-[1600px] mx-auto flex justify-between items-center gap-4">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2 group">
              <span className="h-3 w-3 rounded-full bg-emerald-600 animate-pulse shadow-[0_0_10px_rgba(16,185,129,0.6)]" />
              <h1 className="text-xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
                <Building2 className="h-5 w-5 text-emerald-600" />
                Admin Console
              </h1>
            </Link>
            <Badge tone="emerald">Hospital Command Center</Badge>
          </div>
          <div className="flex items-center gap-3">
            <Badge tone="emerald">
              <ShieldCheck className="h-3 w-3" /> ABDM & DPDP Compliant
            </Badge>
            <PWAInstallButton />
            <LogoutButton />
            <Link
              href="/"
              className="flex items-center gap-1.5 text-xs font-mono font-bold uppercase tracking-wider text-slate-500 hover:text-blue-600 transition-colors"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Home
            </Link>
          </div>
        </div>
      </header>

      <main className="max-w-[1600px] w-full mx-auto p-4 md:p-6 lg:p-8 space-y-6 flex-1">
        {/* Title row */}
        <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3">
          <div>
            <h2 className="text-2xl font-bold tracking-tight text-slate-900">Patient Registry</h2>
            <p className="text-sm font-medium text-slate-500 mt-1">
              Real-time post-discharge cohort · {patients.length} active records · Agent 5 TPA dossier on demand.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {source === 'supabase' ? (
              <Badge tone="emerald"><Database className="h-3 w-3" /> Live · Supabase</Badge>
            ) : source === 'unconfigured' ? (
              <Badge tone="slate"><Database className="h-3 w-3" /> Supabase Not Connected</Badge>
            ) : (
              <Badge tone="slate"><Database className="h-3 w-3" /> Loading Source</Badge>
            )}
            <Badge tone="blue"><Activity className="h-3 w-3" /> TPA Engine Ready</Badge>
          </div>
        </div>

        {/* Data grid
            Layout strategy:
              • <sm (mobile): each row becomes a stacked card. Labels appear
                above each value so the registry stays readable on phones.
              • ≥sm (tablet+): classic 12-col horizontal table, same as before.
            The shared outer container has `overflow-hidden` for rounded corners
            on the data rows — that does NOT prevent horizontal overflow on
            mobile because the rows themselves stack vertically there. */}
        <div className="rounded-3xl border border-slate-200 bg-white shadow-sm overflow-hidden">
          {/* Table header — hidden on mobile, the stacked-card row below
              uses its own inline labels so the user never loses context. */}
          <div className="hidden sm:grid bg-slate-900 px-5 py-3 grid-cols-12 gap-3 text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400">
            <div className="col-span-2">Patient ID</div>
            <div className="col-span-3">ABHA ID · 14 digits</div>
            <div className="col-span-2">Name</div>
            <div className="col-span-2">Diagnosis</div>
            <div className="col-span-1">Status</div>
            <div className="col-span-1">Adherence</div>
            <div className="col-span-1 text-right">TPA Action</div>
          </div>

          {loading ? (
            <div className="p-12 flex flex-col items-center justify-center gap-3 text-slate-400">
              <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
              <p className="text-sm font-mono">Loading patient registry…</p>
            </div>
          ) : fetchError ? (
            <div className="p-12 flex flex-col items-center justify-center gap-3 text-slate-500">
              <div className="h-11 w-11 rounded-2xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center">
                <X className="h-5 w-5 text-rose-500" />
              </div>
              <p className="text-sm font-semibold text-slate-700">Couldn&rsquo;t load the registry</p>
              <p className="text-xs font-mono text-slate-400 max-w-md text-center">{fetchError}</p>
              <p className="text-[11px] font-mono text-slate-400">Ensure the backend is running (uvicorn main:app) so GET /api/patients responds.</p>
            </div>
          ) : patients.length === 0 ? (
            <div className="p-16 flex flex-col items-center justify-center gap-4 text-center">
              <div className="relative">
                <div className="absolute inset-0 rounded-2xl bg-blue-500/10 blur-xl" />
                <div className="relative h-16 w-16 rounded-2xl bg-white border border-slate-200 shadow-sm flex items-center justify-center">
                  <HeartPulse className="h-7 w-7 text-blue-500" />
                </div>
              </div>
              <div className="space-y-1.5 max-w-sm">
                <p className="text-lg font-semibold tracking-tight text-slate-900">
                  No active patients.
                </p>
                <p className="text-sm text-slate-500 leading-relaxed">
                  Upload a discharge summary to begin monitoring.
                </p>
              </div>
              <Link href="/patient">
                <Button variant="primary" size="sm">
                  <ArrowLeft className="h-3.5 w-3.5" /> Go to Patient Portal
                </Button>
              </Link>
              {source === 'unconfigured' && (
                <p className="text-[11px] font-mono text-slate-400 max-w-md">
                  Supabase isn&rsquo;t configured — connect <span className="font-bold">SUPABASE_URL</span> + <span className="font-bold">SUPABASE_KEY</span> in <span className="font-bold">backend/.env</span> to populate live records.
                </p>
              )}
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {patients.map((p, i) => (
                <motion.div
                  key={p.patient_id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: i * 0.04 }}
                  className="px-5 py-4 hover:bg-slate-50 transition-colors group"
                >
                  {/* Mobile-only stacked card (<sm): each label sits above
                      its value. The Generate button is full-width at the
                      bottom for an easy thumb target. */}
                  <div className="flex flex-col gap-3 sm:hidden">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-jetbrains text-sm font-bold text-slate-900">{p.patient_id}</span>
                      <Badge tone={STATUS_TONE[p.status]}>{p.status}</Badge>
                    </div>
                    <div className="flex flex-col gap-1.5 text-xs">
                      <div className="flex justify-between gap-3">
                        <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400">ABHA</span>
                        <span className="font-jetbrains font-bold text-blue-700 tracking-wider truncate">{p.abha_id}</span>
                      </div>
                      <div className="flex justify-between gap-3">
                        <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400">Name</span>
                        <span className="font-bold text-slate-900 truncate">{p.name}</span>
                      </div>
                      <div className="flex justify-between gap-3">
                        <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400">Diagnosis</span>
                        <span className="font-medium text-slate-600 line-clamp-2 text-right">{p.diagnosis}</span>
                      </div>
                      <div className="flex justify-between items-center gap-3">
                        <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-400">Adherence</span>
                        <div className="flex items-center gap-2">
                          <Progress value={p.adherence} tone={p.adherence >= 70 ? 'emerald' : 'rose'} className="w-20" />
                          <span className="text-[11px] font-mono font-bold text-slate-600">{p.adherence}%</span>
                        </div>
                      </div>
                    </div>
                    <motion.button
                      whileTap={{ scale: 0.96 }}
                      onClick={() => openDossier(p)}
                      className="relative w-full inline-flex items-center justify-center gap-1.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-xs font-semibold uppercase tracking-wider px-3 py-2.5 shadow-md shadow-blue-600/30 transition-all"
                    >
                      <span className="absolute inset-0 rounded-xl bg-blue-500/40 blur-md opacity-60 -z-10 animate-pulse" />
                      <Sparkles className="h-3.5 w-3.5" />
                      Generate TPA Dossier
                    </motion.button>
                  </div>

                  {/* ≥sm: classic 12-col table row (unchanged). */}
                  <div className="hidden sm:grid grid-cols-12 gap-3 items-center">
                    <div className="col-span-2">
                      <span className="font-jetbrains text-sm font-bold text-slate-900">{p.patient_id}</span>
                    </div>
                    <div className="col-span-3">
                      <span className="font-jetbrains text-sm font-bold text-blue-700 tracking-wider">{p.abha_id}</span>
                    </div>
                    <div className="col-span-2">
                      <span className="text-sm font-bold text-slate-900">{p.name}</span>
                    </div>
                    <div className="col-span-2">
                      <span className="text-sm font-medium text-slate-600 line-clamp-1">{p.diagnosis}</span>
                    </div>
                    <div className="col-span-1">
                      <Badge tone={STATUS_TONE[p.status]}>{p.status}</Badge>
                    </div>
                    <div className="col-span-1">
                      <div className="flex items-center gap-2">
                        <Progress value={p.adherence} tone={p.adherence >= 70 ? 'emerald' : 'rose'} className="w-16" />
                        <span className="text-[11px] font-mono font-bold text-slate-600">{p.adherence}%</span>
                      </div>
                    </div>
                    <div className="col-span-1 flex justify-end">
                      <motion.button
                        whileTap={{ scale: 0.96 }}
                        onClick={() => openDossier(p)}
                        className="relative inline-flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white text-[10px] font-semibold uppercase tracking-wider px-3 py-2 shadow-md shadow-blue-600/30 transition-all"
                      >
                        <span className="absolute inset-0 rounded-xl bg-blue-500/40 blur-md opacity-60 -z-10 animate-pulse" />
                        <Sparkles className="h-3.5 w-3.5" />
                        Generate
                      </motion.button>
                    </div>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>
      </main>

      {/* ----- ICD-10 Claim Dossier Modal ----- */}
      <AnimatePresence>
        {activePatient && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[90] flex items-center justify-center p-3 sm:p-4 bg-slate-950/70 backdrop-blur-sm"
            onClick={closeDossier}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 16 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.97, y: 12 }}
              transition={{ type: 'spring', stiffness: 320, damping: 30 }}
              onClick={(e) => e.stopPropagation()}
              className="relative w-full max-w-3xl max-h-[88vh] overflow-hidden rounded-3xl border border-sky-500/30 bg-gradient-to-br from-sky-900 via-slate-900 to-slate-950 shadow-2xl flex flex-col"
            >
              {/* Modal header */}
              <div className="flex items-center justify-between gap-3 px-4 py-3 sm:px-6 sm:py-4 border-b border-white/10">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="h-10 w-10 rounded-xl bg-blue-500/15 border border-blue-500/30 flex items-center justify-center shrink-0">
                    <FileText className="h-5 w-5 text-blue-400" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="text-base font-bold tracking-tight text-white flex items-center gap-2 truncate">
                      ICD-10 TPA Insurance Dossier
                      <Badge tone="blue">Agent 5</Badge>
                    </h3>
                    <p className="text-[11px] font-mono text-slate-400 mt-0.5 truncate">
                      {activePatient.patient_id} · <span className="font-jetbrains text-blue-300">{activePatient.abha_id}</span> · {activePatient.name}
                    </p>
                  </div>
                </div>
                <button onClick={closeDossier} className="text-slate-400 hover:text-white transition-colors shrink-0" aria-label="Close">
                  <X className="h-5 w-5" />
                </button>
              </div>

              {/* Modal body */}
              <div className="px-4 py-5 sm:px-6 overflow-y-auto text-white space-y-5">
                {generating ? (
                  <div className="flex flex-col items-center justify-center gap-3 py-16">
                    <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
                    <p className="text-sm font-mono text-slate-300">Agent 5 generating ICD-10 dossier &amp; billing justification…</p>
                    <p className="text-[10px] font-mono text-slate-500">POST /api/claim/generate · abha_id {activePatient.abha_id}</p>
                  </div>
                ) : error ? (
                  <div className="rounded-2xl border border-rose-500/40 bg-rose-950/30 p-4">
                    <p className="text-sm font-bold text-rose-200">{error}</p>
                    <p className="text-xs text-rose-300/70 mt-1 font-mono">The backend returned an error. Verify the backend is running and the ABHA id passes the compliance gate.</p>
                  </div>
                ) : (
                  <>
                    {/* ICD-10 codes */}
                    {icdCodes.length > 0 && (
                      <div>
                        <p className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-500 mb-2">ICD-10 Codes · Medical Necessity</p>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                          {icdCodes.map((c, i) => (
                            <div key={i} className="flex items-center gap-3 rounded-xl border border-white/10 bg-slate-950/50 px-3 py-2.5">
                              <span className="font-jetbrains text-sm font-bold text-blue-300">{c.code}</span>
                              <span className="text-xs font-medium text-slate-300 line-clamp-1">{c.description}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Billing summary */}
                    {billingTotal != null && (
                      <div className="rounded-2xl border border-emerald-500/30 bg-emerald-950/20 p-4">
                        <p className="text-[10px] font-mono font-bold uppercase tracking-wider text-emerald-400/80 mb-1">Estimated TPA Reimbursement</p>
                        <p className="font-jetbrains text-3xl font-bold text-emerald-300">
                          ₹{Number(billingTotal).toLocaleString('en-IN')}
                        </p>
                      </div>
                    )}

                    {/* Inline html_report from the backend (if any) */}
                    {htmlReport && (
                      <div>
                        <p className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-500 mb-2">Generated Justification Report</p>
                        <div
                          className="prose prose-invert max-w-none text-sm text-slate-200 [&_b]:text-white [&_h1]:text-white [&_h2]:text-white [&_h3]:text-white [&_strong]:text-white"
                          dangerouslySetInnerHTML={{ __html: htmlReport }}
                        />
                      </div>
                    )}

                    {/* Fallback dossier object dump when no html_report */}
                    {!htmlReport && dossier && (
                      <div>
                        <p className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-500 mb-2">Dossier Payload</p>
                        <pre className="font-jetbrains text-[11px] leading-relaxed text-slate-300 bg-slate-950/60 border border-white/10 rounded-xl p-4 overflow-x-auto">
                          {JSON.stringify(dossier, null, 2)}
                        </pre>
                      </div>
                    )}

                    {compliance && (
                      <div className="rounded-xl border border-white/10 bg-slate-950/40 p-3">
                        <p className="text-[10px] font-mono font-bold uppercase tracking-wider text-slate-500 mb-1.5">Compliance Metadata</p>
                        <pre className="font-jetbrains text-[10px] text-slate-400 overflow-x-auto">
                          {JSON.stringify(compliance, null, 2)}
                        </pre>
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Modal footer — ABDM/DPDP data-residency footer + actions.
                  Stacks vertically on mobile (compliance badge → detail →
                  action buttons) so nothing clips on narrow viewports. The two
                  action buttons sit side-by-side on ≥sm and stack on mobile;
                  each is shrink-0 + w-full/w-auto so the row can't overflow. */}
              <div className="px-4 py-3 sm:px-6 sm:py-4 border-t border-white/10 bg-slate-950/60 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-2 min-w-0">
                  <div className="flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1.5 self-start">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                    <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-emerald-300">
                      ABDM &amp; DPDP Compliant
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-500">
                    Data residency: India · Consent-gated · Sovereign storage
                  </span>
                </div>
                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 shrink-0">
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    onClick={handleDownloadPDF}
                    disabled={downloading || generating || !dossier}
                    className="w-full sm:w-auto shrink-0"
                  >
                    {downloading ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Download className="h-3.5 w-3.5" />
                    )}
                    {downloading ? 'Downloading…' : 'Download PDF'}
                  </Button>
                  <Button
                    type="button"
                    variant="navy"
                    size="sm"
                    onClick={closeDossier}
                    className="w-full sm:w-auto shrink-0"
                  >
                    Close
                  </Button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}