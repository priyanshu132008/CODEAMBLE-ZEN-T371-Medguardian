'use client';

import React from 'react';
import type { ExtractedData, Medication } from '../Services/api';

export default function Dashboard({ extractedData }: { extractedData: ExtractedData }) {
  return (
    <div className="space-y-6">
      <div className="bg-white/70 backdrop-blur-md border border-slate-200 rounded-3xl p-6 shadow-xl">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-blue-600 block mb-1">Your diagnosis</span>
        <h2 className="text-xl font-semibold text-slate-900 tracking-tight">{extractedData.diagnosis}</h2>
      </div>

      <div className="bg-white/70 backdrop-blur-md border border-slate-200 rounded-3xl shadow-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center">
          <h3 className="font-bold text-sm text-slate-800">Verified Treatment Registry</h3>
          <span className="text-xs font-bold text-blue-600 font-mono bg-blue-50 px-2.5 py-1 rounded-lg">
            {extractedData.medications.length} Prescriptions
          </span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-xs font-medium">
            <thead>
              <tr className="bg-slate-50/50 border-b border-slate-100 text-slate-400 uppercase tracking-wider text-[10px]">
                <th className="px-6 py-3 font-bold">Medication</th>
                <th className="px-6 py-3 font-bold">Dosage</th>
                <th className="px-6 py-3 font-bold">Frequency</th>
                <th className="px-6 py-3 font-bold">Duration</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700">
              {extractedData.medications.map((m: Medication, i: number) => (
                <tr key={i} className="hover:bg-blue-50/30 transition-colors">
                  <td className="px-6 py-4 font-semibold text-slate-900 text-sm">{m.name}</td>
                  <td className="px-6 py-4 font-mono text-slate-600">{m.dosage}</td>
                  <td className="px-6 py-4 text-slate-600">{m.frequency}</td>
                  <td className="px-6 py-4"><span className="bg-slate-100 text-slate-700 font-bold px-2 py-0.5 rounded text-[10px]">{m.duration}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-3xl p-5">
          <h4 className="font-bold text-sm text-amber-900 mb-3 flex items-center gap-2">⚠️ Care Directives</h4>
          <ul className="space-y-2">
            {extractedData.precautions.map((p: string, i: number) => (
              <li key={i} className="flex gap-2 text-xs font-semibold text-slate-700 items-start">
                <span className="text-emerald-600 font-bold">✓</span> {p}
              </li>
            ))}
          </ul>
        </div>
        <div className="bg-red-500/5 border border-red-500/20 rounded-3xl p-5">
          <h4 className="font-bold text-sm text-red-900 mb-3 flex items-center gap-2">🚨 Emergency Flags</h4>
          <ul className="space-y-2">
            {extractedData.warning_signs.map((w: string, i: number) => (
              <li key={i} className="bg-red-500/10 text-red-900 rounded-xl px-3 py-1.5 font-bold text-xs">
                {w}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}