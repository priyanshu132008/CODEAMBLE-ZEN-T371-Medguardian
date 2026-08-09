'use client';

import React, { useMemo, useState } from 'react';
import {
  Building2,
  FileText,
  Loader2,
  X,
  CheckCircle2,
  AlertCircle,
  Mail,
  ShieldCheck,
  Download,
} from 'lucide-react';
import {
  generateClaimDossier,
  downloadClaimPDF,
  getApiErrorMessage,
  type ClaimDossier as ClaimDossierData,
  type ComplianceMeta,
  type ExtractedData,
  type SafetyFlag,
  type TeachBackState,
} from '../Services/api';

interface ClaimDossierProps {
  // Agent 1 output — gates the "Generate" button.
  extractedData: ExtractedData;
  // Agent 2 output — forwarded to the claim engine.
  safetyFlags?: SafetyFlag[];
  // Live Agent 3 teach-back state — forwarded for the medical-necessity rationale.
  teachBackState?: TeachBackState;
  language?: string;
}

// Default to the verified Resend sandbox delivery address so the
// transparent claim-status email actually delivers during the live demo
// (the sandbox sender only delivers to the account owner's verified inbox).
const DEFAULT_PATIENT_EMAIL = 'priyanshucreator3@gmail.com';

export default function ClaimDossier({
  extractedData,
  safetyFlags = [],
  teachBackState,
  language = 'en',
}: ClaimDossierProps) {
  const [patientEmail, setPatientEmail] = useState(DEFAULT_PATIENT_EMAIL);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dossier, setDossier] = useState<ClaimDossierData | null>(null);
  const [htmlReport, setHtmlReport] = useState<string | null>(null);
  const [compliance, setCompliance] = useState<ComplianceMeta | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  // PDF download state — separate from `loading` (which is for dossier
  // generation) so the spinner state is independent. `downloading` only
  // applies inside the modal; the button is the visual cue.
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [lastDownloadName, setLastDownloadName] = useState<string | null>(null);

  const ready = !!extractedData;

  // Assemble the shared contract state object the backend expects.
  const patientData = useMemo(() => ({
    patient_id: 'ui-session',
    extracted: extractedData,
    safety_flags: safetyFlags,
    teach_back: teachBackState || {
      questions_asked: [],
      patient_responses: [],
      understanding_score: 0,
      corrections_given: [],
    },
    language,
  }), [extractedData, safetyFlags, teachBackState, language]);

  const handleGenerate = async () => {
    if (!ready || loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await generateClaimDossier(patientData, patientEmail.trim() || DEFAULT_PATIENT_EMAIL);
      setDossier(result?.dossier ?? null);
      setHtmlReport(result?.html_report ?? null);
      setCompliance(result?.compliance_metadata ?? null);
      if (!result?.html_report) {
        setError('The claim engine returned no report. Check the backend logs.');
      } else {
        setModalOpen(true);
      }
    } catch (err: unknown) {
      setError(getApiErrorMessage(err, 'Claim generation failed.'));
    } finally {
      setLoading(false);
    }
  };

  // PDF download handler. Re-uses the same patient data + email as the
  // dossier so the PDF reflects exactly what the modal is showing. The
  // backend sets `Content-Disposition: attachment` so the browser opens the
  // native Save dialog without us changing the modal state — the modal
  // stays open and the user can download again if needed.
  const handleDownloadPDF = async () => {
    if (downloading) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const filename = await downloadClaimPDF(
        patientData,
        patientEmail.trim() || DEFAULT_PATIENT_EMAIL,
      );
      setLastDownloadName(filename);
    } catch (err: unknown) {
      setDownloadError(
        getApiErrorMessage(err, 'PDF download failed. Please try again.'),
      );
    } finally {
      setDownloading(false);
    }
  };

  return (
    <>
      {/* Agent 5 card */}
      <div className="bg-gradient-to-br from-sky-900 via-slate-900 to-slate-950 border border-sky-500/30 rounded-3xl p-6 text-white shadow-2xl relative overflow-hidden">
        <div className="absolute top-0 right-0 bg-sky-500/10 text-sky-300 text-[10px] font-mono font-bold uppercase tracking-wider px-3 py-1 rounded-bl-xl border-l border-b border-sky-500/20">
          Insurance &amp; Claims
        </div>

        {/* ABDM / DPDP compliance badge — surfaced once a dossier is generated,
            so judges can see the data-residency + de-identification policy. */}
        {compliance && (
          <div className="flex items-center gap-2 mt-1 mb-1 inline-flex w-fit">
            <span className="flex items-center gap-1.5 bg-emerald-500/15 border border-emerald-400/40 text-emerald-300 rounded-full px-3 py-1 text-[11px] font-bold tracking-wide">
              <ShieldCheck className="h-3.5 w-3.5" />
              DPDP &amp; ABDM Compliant
            </span>
            <span className="text-[10px] font-mono text-emerald-200/80">
              {compliance.data_residency}
            </span>
          </div>
        )}

        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-5 mt-2">
          <div className="flex items-start gap-3">
            <div className="h-11 w-11 rounded-2xl bg-sky-500/20 border border-sky-400/30 flex items-center justify-center shrink-0">
              <Building2 className="h-6 w-6 text-sky-300" />
            </div>
            <div>
              <h3 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
                Auto-Claim Engine
              </h3>
              <p className="text-xs text-slate-300 font-medium mt-1">
                We file your TPA insurance dossier automatically — ICD-10 codes, medical necessity, and billing.
              </p>
            </div>
          </div>

          {/* Patient email for the transparent claim-status copy */}
          <div className="w-full sm:w-auto">
            <label className="text-[10px] font-semibold uppercase tracking-widest text-sky-300 block mb-1">
              Patient Email (claim-status copy)
            </label>
            <div className="flex items-center gap-2 bg-slate-950/60 border border-white/10 rounded-xl px-3 py-2 w-full sm:w-72">
              <Mail className="h-4 w-4 text-sky-400 shrink-0" />
              <input
                type="email"
                value={patientEmail}
                onChange={(e) => setPatientEmail(e.target.value)}
                placeholder="patient@example.com"
                className="bg-transparent text-xs text-white font-medium focus:outline-none w-full"
              />
            </div>
          </div>
        </div>

        {/* Action row */}
        <div className="mt-5 flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
          <button
            onClick={handleGenerate}
            disabled={!ready || loading}
            className={`flex items-center justify-center gap-2.5 px-6 py-3.5 rounded-2xl font-semibold text-sm uppercase tracking-wider transition-all duration-300 shadow-md ${
              !ready
                ? 'bg-slate-700/60 text-slate-400 cursor-not-allowed'
                : loading
                  ? 'bg-sky-700 text-white cursor-wait'
                  : 'bg-sky-500 hover:bg-sky-400 text-white shadow-sky-500/30 hover:shadow-lg'
            }`}
          >
            {loading ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin" />
                Generating Dossier…
              </>
            ) : (
              <>
                <FileText className="h-5 w-5" />
                Generate TPA Insurance Dossier
              </>
            )}
          </button>

          {!ready && (
            <span className="text-[11px] font-mono text-slate-400 flex items-center gap-1.5">
              <AlertCircle className="h-3.5 w-3.5" />
              Upload a discharge summary (Agent 1) to enable.
            </span>
          )}

          {ready && !loading && dossier && !error && (
            <button
              onClick={() => setModalOpen(true)}
              className="flex items-center gap-2 px-4 py-3.5 rounded-2xl font-bold text-xs uppercase tracking-wider bg-white/10 hover:bg-white/15 text-sky-200 border border-sky-400/20 transition-all"
            >
              <ShieldCheck className="h-4 w-4" />
              View Full Report
            </button>
          )}
        </div>

        {/* Inline status / errors */}
        {error && (
          <div className="mt-4 flex items-center gap-2 text-xs font-semibold text-red-300 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </div>
        )}

        {ready && !loading && dossier && !error && (
          <div className="mt-4 flex flex-wrap items-center gap-2 text-[11px] font-mono">
            <span className="flex items-center gap-1.5 bg-emerald-500/10 border border-emerald-400/20 text-emerald-300 rounded-lg px-2.5 py-1">
              <CheckCircle2 className="h-3.5 w-3.5" />
              Dossier generated
            </span>
            {Array.isArray(dossier.icd10_codes) && dossier.icd10_codes.length > 0 && (
              <span className="bg-sky-500/10 border border-sky-400/20 text-sky-200 rounded-lg px-2.5 py-1">
                ICD-10: {dossier.icd10_codes.map((c) => c.code).join(', ')}
              </span>
            )}
            {dossier.claim_summary?.total_estimated_cost && (
              <span className="bg-amber-500/10 border border-amber-400/20 text-amber-200 rounded-lg px-2.5 py-1">
                Total: {dossier.claim_summary.total_estimated_cost}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Report modal — renders the backend's html_report via dangerouslySetInnerHTML
          inside an isolated, scrollable Tailwind container. */}
      {modalOpen && htmlReport && (
        <div
          className="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setModalOpen(false)}
        >
          <div
            className="bg-white rounded-3xl shadow-2xl w-full max-w-4xl max-h-[88vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 bg-slate-50">
              <div className="flex items-center gap-2.5">
                <div className="h-9 w-9 rounded-xl bg-sky-600 flex items-center justify-center">
                  <FileText className="h-5 w-5 text-white" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-900 text-base tracking-tight">Claim Summary Report</h3>
                  <p className="text-[10px] font-mono text-slate-500 uppercase tracking-wider">
                    Auto-Claim &amp; Insurance Justification Dossier
                  </p>
                </div>
              </div>
              <button
                onClick={() => setModalOpen(false)}
                className="h-9 w-9 rounded-xl bg-slate-200 hover:bg-slate-300 text-slate-700 flex items-center justify-center transition-colors"
                aria-label="Close report"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="overflow-y-auto bg-slate-50 flex-1">
              {/* The backend returns a complete styled HTML report; inject it
                  verbatim. Its inline <style> scopes the report's own tables. */}
              <div
                className="claim-report-render"
                dangerouslySetInnerHTML={{ __html: htmlReport }}
              />
            </div>

            {/* ABDM / DPDP compliance footer — full metadata for the judges. */}
            {compliance && (
              <div className="px-5 py-3 border-t border-slate-200 bg-emerald-50 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                <span className="flex items-center gap-1.5 text-emerald-700 font-bold text-xs">
                  <ShieldCheck className="h-4 w-4" />
                  DPDP &amp; ABDM Compliant
                </span>
                <span className="text-[11px] font-mono text-slate-600">
                  ABHA:{' '}
                  <span className="font-semibold text-slate-800">
                    {compliance.abdm_abha_id ?? '—'}
                  </span>
                </span>
                <span className="text-[11px] font-mono text-slate-600">
                  Consent:{' '}
                  <span className="font-semibold text-emerald-700">
                    {compliance.dpdp_consent ? 'Granted' : 'Denied'}
                  </span>
                </span>
                <span className="text-[11px] font-mono text-slate-600">
                  Residency:{' '}
                  <span className="font-semibold text-slate-800">
                    {compliance.data_residency}
                  </span>
                </span>
                <span className="text-[11px] font-mono text-slate-600">
                  Cloud:{' '}
                  <span className="font-semibold text-slate-800">
                    {compliance.cloud_transmission}
                  </span>
                </span>
              </div>
            )}

            {/* Action footer — Download PDF (primary, sky tone to match the
                card's branding) and Close (secondary, slate).
                Layout strategy:
                  • Mobile (<sm): status message sits ABOVE the buttons, full-width,
                    so neither button is ever pushed off-screen.
                  • ≥sm: status sits to the left of the buttons, taking whatever
                    horizontal space remains; buttons are `shrink-0` so they
                    can never be clipped even if the status text is long.
                The download button has its own busy state so the modal doesn't
                flicker and stays interactive — the browser handles the Save
                dialog natively via Content-Disposition, so React state is never
                affected by the download itself. */}
            <div className="px-5 py-3 border-t border-slate-200 bg-white flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div className="min-w-0 sm:flex-1">
                {downloadError ? (
                  <span className="flex items-center gap-1.5 text-xs text-rose-600">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">{downloadError}</span>
                  </span>
                ) : lastDownloadName ? (
                  <span className="flex items-center gap-1.5 text-xs text-emerald-700">
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">
                      Saved as <span className="font-mono font-semibold">{lastDownloadName}</span>
                    </span>
                  </span>
                ) : (
                  <span className="text-[11px] font-mono text-slate-400">
                    Real selectable-text PDF (A4) — for TPA submission
                  </span>
                )}
              </div>
              {/* `shrink-0` on every button keeps them on-screen even if the
                  status text above is wide; `w-full sm:w-auto` makes them
                  full-width on mobile (easy thumb target) and inline on desktop. */}
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={handleDownloadPDF}
                  disabled={downloading}
                  className={`inline-flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl font-bold text-xs uppercase tracking-wider transition-all duration-200 shadow-sm w-full sm:w-auto shrink-0 ${
                    downloading
                      ? 'bg-sky-700 text-white cursor-wait'
                      : 'bg-sky-600 hover:bg-sky-700 text-white shadow-sky-500/20'
                  }`}
                  aria-label="Download Claim Summary Report as PDF"
                >
                  {downloading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Downloading…
                    </>
                  ) : (
                    <>
                      <Download className="h-4 w-4" />
                      Download PDF
                    </>
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setModalOpen(false)}
                  className="inline-flex items-center justify-center px-4 py-2.5 rounded-xl font-bold text-xs uppercase tracking-wider bg-slate-100 hover:bg-slate-200 text-slate-700 transition-colors w-full sm:w-auto shrink-0"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}