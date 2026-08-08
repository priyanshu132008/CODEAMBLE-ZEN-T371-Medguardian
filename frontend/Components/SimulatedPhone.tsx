'use client';

import React, { useState, useEffect } from 'react';
import { getMockReminders, simulateEscalation } from '../Services/api';

export default function SimulatedPhone({ demoMode }: { demoMode: boolean }) {
  const [messages, setMessages] = useState<any[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchReminders = async () => {
      try {
        if (demoMode) {
          setMessages([{ role: 'system', message: '[MedGuardian Engine] Daily Alert: Hello patient, please make sure you ingest your 75mg dosage of Clopidogrel now.' }]);
          return;
        }
        const res = await getMockReminders();
        setMessages(res.map((m: any) => ({
          role: m.role === 'patient' ? 'patient' : 'system',
          message: m.content || m.message
        })));
      } catch {
        setMessages([{ role: 'system', message: '[MedGuardian Engine] Daily Alert: Hello patient, please make sure you ingest your 75mg dosage of Clopidogrel now.' }]);
      }
    };
    fetchReminders();
  }, [demoMode]);

  const onSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userText = input.trim();
    setInput('');
    setLoading(true);
    setMessages(prev => [...prev, { role: 'patient', message: userText }]);

    if (demoMode && userText.toLowerCase().includes('chest pain')) {
      setTimeout(() => {
        setMessages(prev => [...prev, {
          role: 'system',
          message: '🚨 CRITICAL RED ESCALATION: Patient reports chest pain alongside historic Post-Myocardial Infarction tracking logs. Instantly routing tele-health vectors and alerting emergency responder dispatch matrices.',
          highRisk: true
        }]);
        setLoading(false);
      }, 800);
      return;
    }

    try {
      const res = await simulateEscalation(userText);
      setMessages(prev => [...prev, {
        role: 'system',
        message: res.response || res.message,
        highRisk: res.escalation_level === 'high'
      }]);
    } catch {
      setMessages(prev => [...prev, {
        role: 'system',
        message: '⚠️ Local Fallback: High risk parameter caught. Alerting health providers.',
        highRisk: true
      }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full flex justify-center">
      {/* Smartphone Chassis frame design */}
      <div className="w-full max-w-[340px] bg-slate-950 p-3.5 rounded-[50px] shadow-2xl border-4 border-slate-800 relative ring-1 ring-white/10">
        <div className="absolute top-6 left-1/2 -translate-x-1/2 w-28 h-4 bg-slate-950 rounded-full z-20 flex items-center justify-center">
          <div className="w-12 h-1 bg-slate-800 rounded-full" />
        </div>

        <div className="w-full h-[600px] bg-slate-900 rounded-[36px] overflow-hidden flex flex-col relative pt-6 border border-white/5">
          <div className="bg-slate-950 text-white px-4 py-3 border-b border-white/5 flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            <div>
              <h4 className="text-xs font-bold tracking-tight">MedGuardian Automation</h4>
              <p className="text-[9px] font-mono text-slate-400">Patient Continuous Monitoring</p>
            </div>
          </div>

          <div className="flex-1 p-3 overflow-y-auto space-y-3 font-medium text-xs bg-slate-950/40">
            {messages.map((m, idx) => (
              <div key={idx} className={`flex ${m.role === 'patient' ? 'justify-end' : 'justify-start'}`}>
                <div className={`p-3 rounded-2xl max-w-[85%] leading-relaxed ${
                  m.role === 'patient' 
                    ? 'bg-blue-600 text-white rounded-tr-none' 
                    : m.highRisk 
                      ? 'bg-red-500 text-white rounded-tl-none font-bold shadow-[0_0_15px_rgba(239,68,68,0.4)] border border-red-400 animate-pulse' 
                      : 'bg-slate-800 text-slate-100 rounded-tl-none border border-white/5'
                }`}>
                  <p>{m.message}</p>
                </div>
              </div>
            ))}
          </div>

          <form onSubmit={onSend} className="p-2 bg-slate-950 border-t border-white/5 flex gap-1 items-center">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type (e.g., 'I have chest pain')"
              className="flex-1 bg-slate-900 border border-white/10 rounded-full px-3 py-2 text-xs text-white focus:outline-hidden focus:border-blue-500"
            />
            <button type="submit" className="w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0">
              🚀
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}