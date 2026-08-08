'use client';

import React, { useCallback, useRef, useState } from 'react';
import { uploadDocument } from '../Services/api';

// Pre-cached verified extraction payload for DEMO MODE. Lets us bypass the
// (possibly slow/queued) backend entirely and show the full pipeline instantly
// during the live presentation. Matches the `extracted` contract in context.md.
const CACHED_EXTRACTED = {
  diagnosis: 'Type 2 Diabetes & Post-Myocardial Infarction',
  medications: [
    { name: 'Clopidogrel', dosage: '75mg', frequency: 'Once daily', duration: '30 days' },
    { name: 'Omeprazole', dosage: '40mg', frequency: 'Once daily', duration: '14 days' },
    { name: 'Metformin', dosage: '500mg', frequency: 'Twice daily after meals', duration: '90 days' },
  ],
  precautions: ['Monitor blood sugar daily', 'No heavy lifting'],
  follow_up_date: '2026-08-15',
  warning_signs: ['Chest pain', 'Extreme dizziness', 'Blurred vision'],
};

const DEMO_DELAY_MS = 1500; // brief "Agent 1 processing document..." animation for realism

interface UploadZoneProps {
  onExtracted: (extracted: any, fullState: any) => void;
  demoMode?: boolean;
}

export default function UploadZone({ onExtracted, demoMode = false }: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const ACCEPTED = 'image/jpeg,image/png';

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);

      if (!['image/jpeg', 'image/png'].includes(file.type)) {
        setError('Please upload a JPG or PNG photo of the discharge summary.');
        return;
      }

      setFileName(file.name);
      setUploading(true);
      try {
        if (demoMode) {
          // DEMO MODE: bypass the network entirely. Show a brief processing
          // animation, then return the pre-cached verified payload instantly.
          await new Promise((r) => setTimeout(r, DEMO_DELAY_MS));
          onExtracted(CACHED_EXTRACTED, null);
          return; // success: parent swaps in the dashboard, unmounting this component
        }

        // LIVE MODE: real async OCR call to the backend.
        const data = await uploadDocument(file);
        // The contract returns { patient_id, extracted, safety_flags, teach_back, language }.
        const extracted = data?.extracted ?? data;
        onExtracted(extracted, data);
        return; // success: parent swaps in the dashboard, which unmounts this component
      } catch (err: any) {
        // Surface the real failure to the console so silent "infinite spinner"
        // bugs are diagnosable, and always release the loading state.
        console.error('[UploadZone] /api/upload failed:', err);
        const detail = err?.response?.data?.detail || err?.message || 'Upload failed.';
        setError(typeof detail === 'string' ? detail : 'Upload failed.');
      } finally {
        // Belt-and-suspenders: the spinner can never get stuck on, regardless
        // of which path (success/error/throw) the request takes.
        setUploading(false);
      }
    },
    [onExtracted, demoMode]
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
          <span>INTAKE LAYER: AGENT 1 OCR DOCUMENT UPLOAD</span>
        </div>
        <span className="text-blue-400 font-bold uppercase bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">
          POST /api/upload
        </span>
      </div>

      <div className="p-8 md:p-12 flex flex-col items-center justify-center text-center min-h-[280px]">
        {uploading ? (
          <div className="flex flex-col items-center gap-4">
            <div className="h-12 w-12 rounded-full border-4 border-purple-200 border-t-purple-500 animate-spin" />
            <div>
              <p className="text-lg font-black text-white tracking-tight">
                Agent 1 processing document...
              </p>
              <p className="text-xs font-mono text-slate-400 mt-1">
                Vision OCR extracting discharge summary &rarr; structured JSON
              </p>
              {fileName && (
                <p className="text-[11px] font-mono text-purple-400 mt-2 truncate max-w-[280px]">
                  {fileName}
                </p>
              )}
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-4">
            <div className="h-16 w-16 rounded-2xl bg-blue-600/10 text-blue-600 flex items-center justify-center text-3xl shadow-inner">
              📄
            </div>
            <div>
              <h3 className="text-xl font-black text-slate-900 tracking-tight">
                Upload Discharge Summary
              </h3>
              <p className="text-sm font-medium text-slate-500 mt-1 max-w-md">
                Drag &amp; drop a photo of the patient&rsquo;s discharge sheet here,
                or click the button below. Handwritten sheets are supported via
                Agent 1 vision OCR.
              </p>
            </div>
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              className="px-6 py-3 rounded-2xl bg-blue-600 hover:bg-blue-700 text-white font-black text-sm uppercase tracking-wider shadow-md shadow-blue-600/20 transition-all"
            >
              Upload Discharge Summary
            </button>
            {error && (
              <p className="text-xs font-semibold text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">
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