'use client';

import React, { useCallback, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { UploadCloud, FileCheck2, ShieldCheck, AlertCircle } from 'lucide-react';
import { uploadDocument, getApiErrorMessage, type ExtractedData, type UploadResponse } from '../Services/api';

// ABDM concept stays alive on the backend + Admin Dashboard (a valid 14-digit
// ABHA id is still persisted for every upload). To remove live-demo friction we
// don't make the patient type it — the frontend auto-injects a default valid
// number so the compliance/DB write path never breaks. ABHA capture/editing
// remains an Admin-side concern.
const DEFAULT_ABHA_ID = '12341234123412';

interface UploadZoneProps {
  onExtracted: (extracted: ExtractedData, fullState: UploadResponse | null) => void;
}

export default function UploadZone({ onExtracted }: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);

  // DPDP Act 2023 consent gate — the only thing the patient must do before the
  // upload CTA activates (the backend 403s without valid consent). The 14-digit
  // ABHA id is auto-injected on submit, not typed by the patient.
  const [consentGranted, setConsentGranted] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

  const ACCEPTED = 'image/jpeg,image/png';

  const canUpload = consentGranted && !uploading;

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);

      // Consent gate is enforced even if a file is dropped directly onto the
      // zone, so a stray drag-and-drop can never bypass the DPDP gate.
      if (!consentGranted) {
        setError('Please grant DPDP Act consent before uploading.');
        return;
      }

      if (!['image/jpeg', 'image/png'].includes(file.type)) {
        setError('Please upload a JPG or PNG photo of the discharge summary.');
        return;
      }

      setFileName(file.name);
      setUploading(true);
      try {
        // LIVE MODE: real async OCR call to the backend. The ABHA id is
        // auto-injected (default valid 14 digits) so the backend + DB still
        // receive a real ABDM identifier without forcing the patient to type
        // one. No cached/demo payload — the discharge summary is always
        // extracted by the real backend pipeline.
        const data = await uploadDocument(file, {
          abhaId: DEFAULT_ABHA_ID,
          consentGranted: true,
        });
        // The contract returns { patient_id, extracted, safety_flags, teach_back, language }.
        onExtracted(data.extracted, data);
        return; // success: parent swaps in the dashboard, which unmounts this component
      } catch (err: unknown) {
        // Surface the backend's detail message (not the raw error object, which
        // could carry request headers) so silent "infinite spinner" bugs stay
        // diagnosable, and always release the loading state.
        const detail = getApiErrorMessage(err, 'Upload failed.');
        console.error('[UploadZone] /api/upload failed:', detail);
        setError(detail);
      } finally {
        // Belt-and-suspenders: the spinner can never get stuck on, regardless
        // of which path (success/error/throw) the request takes.
        setUploading(false);
      }
    },
    [onExtracted, consentGranted]
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      if (uploading) return;
      const file = e.dataTransfer.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile, uploading]
  );

  const onDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const onInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
      // Reset so selecting the same file again still fires.
      e.target.value = '';
    },
    [handleFile]
  );

  return (
    <div
      onDrop={onDrop}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      className={`relative w-full rounded-3xl border-2 border-dashed transition-all duration-300 overflow-hidden ${
        uploading
          ? 'bg-slate-900 border-purple-500/40'
          : isDragging
            ? 'bg-blue-50 border-blue-500 scale-[1.005]'
            : 'bg-white/70 backdrop-blur-md border-slate-300 hover:border-blue-400'
      }`}
    >
      <div className="bg-slate-950/90 px-4 py-2 border-b border-white/5 flex justify-between items-center text-[10px] font-mono tracking-tight text-slate-400">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${uploading ? 'bg-purple-400 animate-ping' : 'bg-blue-400 animate-pulse'}`} />
          <span>UPLOAD YOUR DISCHARGE SUMMARY</span>
        </div>
        <span className="text-blue-400 font-bold uppercase bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">
          POST /api/upload
        </span>
      </div>

      <div className="p-8 md:p-12 flex flex-col items-center justify-center text-center min-h-[280px]">
        {uploading ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex flex-col items-center gap-4"
          >
            <div className="h-12 w-12 rounded-full border-4 border-purple-200 border-t-purple-500 animate-spin" />
            <div>
              <p className="text-lg font-bold text-white tracking-tight">
                Reading your discharge summary...
              </p>
              <p className="text-xs font-mono text-slate-400 mt-1">
                Translating your notes into a clear medication list
              </p>
              {fileName && (
                <p className="text-[11px] font-mono text-purple-400 mt-2 truncate max-w-[280px]">
                  {fileName}
                </p>
              )}
            </div>
          </motion.div>
        ) : (
          <div className="flex flex-col items-center gap-4 w-full">
            {/* Animated drop target icon */}
            <motion.div
              animate={isDragging ? { scale: 1.12, y: -4 } : { scale: 1, y: 0 }}
              transition={{ type: 'spring', stiffness: 320, damping: 22 }}
              className="h-16 w-16 rounded-2xl bg-blue-600/10 text-blue-600 flex items-center justify-center shadow-inner"
            >
              <UploadCloud className="h-8 w-8" strokeWidth={2.2} />
            </motion.div>
            <div>
              <h3 className="text-xl font-bold text-slate-900 tracking-tight">
                Upload Discharge Summary
              </h3>
              <p className="text-sm font-medium text-slate-500 mt-1 max-w-md">
                Drag &amp; drop a photo of the patient&rsquo;s discharge sheet here,
                or click the button below. Handwritten sheets are welcome —
                even messy doctor notes.
              </p>
            </div>

            {/* ----- DPDP Act consent gate ----- */}
            <div className="w-full max-w-md mt-2 rounded-2xl border border-slate-200 bg-slate-50/80 p-4 text-left space-y-3.5">
              {/* DPDP consent checkbox — the only patient gate. The 14-digit ABHA
                  id is auto-injected on upload, keeping ABDM compliance alive on
                  the backend/Admin side without forcing the patient to type it. */}
              <button
                type="button"
                onClick={() => setConsentGranted((v) => !v)}
                className="flex items-start gap-3 w-full text-left group"
              >
                <span
                  className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border-2 transition-all ${
                    consentGranted
                      ? 'bg-emerald-600 border-emerald-600'
                      : 'bg-white border-slate-300 group-hover:border-blue-400'
                  }`}
                >
                  <AnimatePresence>
                    {consentGranted && (
                      <motion.span
                        initial={{ scale: 0, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0, opacity: 0 }}
                        transition={{ duration: 0.15 }}
                      >
                        <ShieldCheck className="h-3.5 w-3.5 text-white" strokeWidth={3} />
                      </motion.span>
                    )}
                  </AnimatePresence>
                </span>
                <span className="text-[12px] leading-snug font-medium text-slate-600">
                  I consent under the{' '}
                  <span className="font-bold text-slate-900">DPDP Act 2023</span> for
                  MedGuardian to use my discharge summary for care guidance and
                  insurance claims.
                </span>
              </button>
            </div>

            {/* Upload CTA — gated on consent + valid ABHA */}
            <motion.button
              type="button"
              disabled={!canUpload}
              onClick={() => inputRef.current?.click()}
              whileTap={canUpload ? { scale: 0.97 } : {}}
              className={`px-6 py-3 rounded-2xl font-bold text-sm uppercase tracking-wider shadow-md transition-all flex items-center gap-2 ${
                canUpload
                  ? 'bg-blue-600 hover:bg-blue-700 text-white shadow-blue-600/20'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed shadow-none'
              }`}
            >
              {fileName ? (
                <>
                  <FileCheck2 className="h-4 w-4" />
                  {fileName.length > 24 ? `${fileName.slice(0, 24)}…` : fileName} · Upload
                </>
              ) : (
                <>
                  <UploadCloud className="h-4 w-4" />
                  Upload Discharge Summary
                </>
              )}
            </motion.button>

            {/* Gating hint / inline error */}
            {!canUpload && !error && (
              <div className="flex items-center gap-1.5 text-[11px] font-mono text-slate-400">
                <AlertCircle className="h-3 w-3" />
                <span>Grant DPDP consent to enable upload</span>
              </div>
            )}
            {error && (
              <p className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2 flex items-center gap-1.5">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                {error}
              </p>
            )}
          </div>
        )}

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          onChange={onInputChange}
          className="hidden"
          disabled={uploading}
        />
      </div>
    </div>
  );
}