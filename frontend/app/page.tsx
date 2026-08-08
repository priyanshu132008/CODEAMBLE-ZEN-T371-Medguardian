'use client';

import React from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import {
  HeartPulse,
  ShieldCheck,
  ScanLine,
  ShieldAlert,
  MessageSquareText,
  Receipt,
  ArrowRight,
  Sparkles,
  Lock,
  CheckCircle2,
} from 'lucide-react';
import { Button } from '@/Components/ui/button';
import { Badge } from '@/Components/ui/badge';
import PWAInstallButton from '@/Components/PWAInstallButton';
import { cn } from '@/lib/utils';

/**
 * MedGuardian public landing — benefit-led, reassuring, Stripe/Vercel-soft.
 *
 * Humanized copy (no AI/dev jargon on the public surface), an asymmetric
 * feature section, and softer typography/spacing. Deep Navy + soft white
 * palette, JetBrains Mono reserved for data chips only.
 */

// Asymmetric feature tiles — human names, no "Agent"/"OCR"/"JSON" jargon.
const FEATURES = [
  {
    icon: ScanLine,
    title: 'Smart Prescription Scanner',
    desc: 'Snap a photo of messy, handwritten discharge papers and get a clear, structured medication list in seconds — doses, timings, and warnings all translated.',
    span: 'lg:col-span-2',
    accent: 'from-blue-500/15 to-indigo-500/5',
    iconColor: 'text-blue-500',
    chip: 'Photo or PDF',
  },
  {
    icon: ShieldAlert,
    title: 'Safety Check',
    desc: 'Catches dangerous conflicts before they reach you — like an antibiotic prescribed despite a penicillin allergy — and flags them loud and clear.',
    span: 'lg:col-span-1',
    accent: 'from-rose-500/15 to-rose-500/5',
    iconColor: 'text-rose-500',
    chip: 'Real-time check',
  },
  {
    icon: MessageSquareText,
    title: 'Voice Assistant',
    desc: 'A friendly multilingual guide confirms, in your own words, that you understand how to take each medicine — so nothing gets lost in translation.',
    span: 'lg:col-span-1',
    accent: 'from-violet-500/15 to-violet-500/5',
    iconColor: 'text-violet-500',
    chip: '12 languages',
  },
  {
    icon: Receipt,
    title: 'Auto-Claim Engine',
    desc: 'The moment care is verified, your insurance paperwork is done — a complete claim dossier with the right codes is filed to your TPA automatically.',
    span: 'lg:col-span-2',
    accent: 'from-emerald-500/15 to-emerald-500/5',
    iconColor: 'text-emerald-500',
    chip: 'TPA-ready',
  },
];

const STEPS = [
  { n: '1', title: 'Upload your discharge sheet', desc: 'A photo is all it takes — handwritten or printed.' },
  { n: '2', title: 'We build your daily plan', desc: 'Clear timings, allergy checks, and voice guidance.' },
  { n: '3', title: 'Claims file themselves', desc: 'Insurance dossiers go to your TPA automatically.' },
];

export default function Home() {
  return (
    <div className="min-h-screen bg-[#fafbfc] text-slate-900 antialiased relative overflow-x-hidden">
      {/* ===== Fixed glassmorphism navbar ===== */}
      <header className="fixed top-0 inset-x-0 z-50">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="mt-3 flex items-center justify-between rounded-2xl border border-slate-200/80 bg-white/80 backdrop-blur-xl shadow-sm px-4 py-2.5">
            <Link href="/" className="flex items-center gap-2.5">
              <span className="h-8 w-8 rounded-xl bg-slate-900 flex items-center justify-center">
                <HeartPulse className="h-4 w-4 text-blue-400" />
              </span>
              <div className="leading-none">
                <span className="block text-sm font-bold tracking-tight text-slate-900">MedGuardian</span>
                <span className="block text-[9px] font-mono uppercase tracking-wider text-slate-400">Care at home</span>
              </div>
            </Link>

            <div className="hidden md:flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1">
                <ShieldCheck className="h-3 w-3 text-emerald-600" />
                <span className="text-[10px] font-semibold text-emerald-700">ABDM &amp; DPDP Compliant</span>
              </span>
            </div>

            <div className="flex items-center gap-2">
              <PWAInstallButton />
              <Link href="/patient"><Button variant="ghost" size="sm">Patient Portal</Button></Link>
              <Link href="/admin"><Button variant="outline" size="sm">Admin Console</Button></Link>
              <Link href="/login"><Button variant="primary" size="sm">Sign In <ArrowRight className="h-3.5 w-3.5" /></Button></Link>
            </div>
          </div>
        </div>
      </header>

      {/* ===== Hero ===== */}
      <section className="relative pt-36 pb-24 px-4 sm:px-6">
        <div className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="absolute top-20 -left-16 h-72 w-72 rounded-full bg-blue-400/20 blur-3xl" />
          <div className="absolute top-32 right-0 h-80 w-80 rounded-full bg-indigo-400/15 blur-3xl" />
          <div className="absolute bottom-0 left-1/3 h-64 w-64 rounded-full bg-emerald-300/10 blur-3xl" />
        </div>

        <div className="relative mx-auto max-w-4xl text-center">
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/80 backdrop-blur px-3.5 py-1.5 mb-7"
          >
            <Sparkles className="h-3.5 w-3.5 text-blue-500" />
            <span className="text-[11px] font-semibold tracking-tight text-slate-600">
              Trusted by care teams · Built for Indian healthcare
            </span>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, ease: 'easeOut' }}
            className="text-4xl sm:text-6xl font-semibold tracking-tight text-slate-900 leading-[1.08]"
          >
            Hospital-grade care,
            <br />
            <span className="bg-gradient-to-r from-blue-600 via-indigo-600 to-emerald-600 bg-clip-text text-transparent">
              simplified for home.
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.08, ease: 'easeOut' }}
            className="mt-6 max-w-2xl mx-auto text-lg sm:text-xl font-normal text-slate-500 leading-relaxed"
          >
            MedGuardian translates messy discharge papers into clear daily care
            plans, keeping you safe and on track.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55, delay: 0.16, ease: 'easeOut' }}
            className="mt-9 flex flex-col sm:flex-row items-center justify-center gap-3"
          >
            <Link href="/login"><Button size="lg" variant="primary">Get started <ArrowRight className="h-4 w-4" /></Button></Link>
            <Link href="/patient"><Button size="lg" variant="outline">See how it works</Button></Link>
          </motion.div>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.3 }}
            className="mt-5 text-xs font-medium text-slate-400"
          >
            Free for patients · No app to install · Works on any phone
          </motion.p>
        </div>
      </section>

      {/* ===== Asymmetric feature section ===== */}
      <section className="relative px-4 sm:px-6 pb-20">
        <div className="mx-auto max-w-6xl">
          <div className="max-w-2xl mb-10">
            <p className="text-sm font-semibold text-blue-600 mb-2">How it helps</p>
            <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight text-slate-900">
              Everything you need to recover with confidence.
            </h2>
            <p className="mt-3 text-base text-slate-500 leading-relaxed">
              Four quiet, reliable layers that work in the background — from reading
              your prescription to filing your claim.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {FEATURES.map((f, i) => {
              const Icon = f.icon;
              return (
                <motion.div
                  key={f.title}
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true, margin: '-60px' }}
                  transition={{ duration: 0.45, delay: i * 0.07, ease: 'easeOut' }}
                  whileHover={{ y: -4 }}
                  className={cn(
                    'group relative rounded-2xl border border-slate-200 bg-white p-7 shadow-sm hover:shadow-md transition-all duration-300 overflow-hidden',
                    f.span
                  )}
                >
                  <div className={cn('absolute inset-0 bg-gradient-to-br opacity-60', f.accent)} />
                  <div className="relative">
                    <div className="flex items-center justify-between mb-5">
                      <div className={cn('h-11 w-11 rounded-xl bg-white border border-slate-200 flex items-center justify-center shadow-sm', f.iconColor)}>
                        <Icon className="h-5 w-5" />
                      </div>
                      <span className="font-mono text-[10px] font-semibold uppercase tracking-wider text-slate-400 bg-white/70 border border-slate-200 px-2 py-1 rounded-full">
                        {f.chip}
                      </span>
                    </div>
                    <h3 className="text-xl font-semibold tracking-tight text-slate-900">{f.title}</h3>
                    <p className="mt-2.5 text-sm text-slate-500 leading-relaxed">{f.desc}</p>
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>
      </section>

      {/* ===== How it works (3 steps) ===== */}
      <section className="relative px-4 sm:px-6 pb-20">
        <div className="mx-auto max-w-5xl">
          <div className="rounded-3xl border border-slate-200 bg-white p-8 sm:p-12 shadow-sm">
            <h2 className="text-2xl sm:text-3xl font-semibold tracking-tight text-slate-900 text-center">
              Three simple steps, one calm recovery.
            </h2>
            <div className="mt-10 grid grid-cols-1 md:grid-cols-3 gap-8">
              {STEPS.map((s, i) => (
                <motion.div
                  key={s.n}
                  initial={{ opacity: 0, y: 16 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ duration: 0.4, delay: i * 0.1 }}
                  className="text-center"
                >
                  <div className="mx-auto mb-4 h-10 w-10 rounded-full bg-slate-900 text-white font-semibold flex items-center justify-center">
                    {s.n}
                  </div>
                  <h3 className="text-base font-semibold text-slate-900">{s.title}</h3>
                  <p className="mt-1.5 text-sm text-slate-500 leading-relaxed">{s.desc}</p>
                </motion.div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ===== CTA ===== */}
      <section className="relative px-4 sm:px-6 pb-24">
        <div className="mx-auto max-w-4xl">
          <div className="relative rounded-3xl border border-slate-800 bg-gradient-to-br from-slate-900 to-indigo-950 px-8 py-14 sm:px-14 text-center shadow-xl overflow-hidden">
            <div className="pointer-events-none absolute -top-20 left-1/2 -translate-x-1/2 h-56 w-[36rem] rounded-full bg-blue-500/20 blur-3xl" />
            <div className="relative">
              <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 mb-5">
                <Lock className="h-3.5 w-3.5 text-emerald-400" />
                <span className="text-[11px] font-semibold tracking-tight text-emerald-300">
                  Consent-gated · Sovereign storage · Audit-ready
                </span>
              </div>
              <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight text-white">
                Your recovery, guided and covered.
              </h2>
              <p className="mt-3 max-w-lg mx-auto text-base text-slate-300 leading-relaxed">
                Sign in to access your care plan, or explore the admin console to see
                the whole ward at a glance.
              </p>
              <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3">
                <Link href="/login"><Button size="lg" variant="primary">Sign in to continue <ArrowRight className="h-4 w-4" /></Button></Link>
                <Link href="/admin"><Button size="lg" variant="outline" className="bg-white/10 border-white/20 text-white hover:bg-white/20 hover:border-white/40">Admin Console</Button></Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ===== Footer ===== */}
      <footer className="border-t border-slate-200 bg-white/60 px-4 sm:px-6 py-8">
        <div className="mx-auto max-w-6xl flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-slate-500">
            <HeartPulse className="h-4 w-4 text-blue-600" />
            <span className="text-sm font-semibold text-slate-700">MedGuardian</span>
            <span className="text-xs text-slate-400">· Care at home, claims on time.</span>
          </div>
          <div className="flex items-center gap-5 text-[11px] font-medium text-slate-500">
            <span className="flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> ABDM</span>
            <span className="flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> DPDP Act 2023</span>
            <span className="flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5 text-emerald-500" /> India data residency</span>
          </div>
        </div>
      </footer>
    </div>
  );
}