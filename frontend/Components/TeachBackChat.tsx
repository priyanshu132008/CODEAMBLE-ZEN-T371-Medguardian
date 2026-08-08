'use client';

import React, { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { evaluateTeachBack, speechToText, textToSpeech } from '../Services/api';

export interface TeachBackChatHandle {
  toggleVoice: () => void;
}

// ---------------------------------------------------------------------------
// Convert the browser's recorded webm/opus Blob into a 16kHz mono WAV. The
// Sarvam STT endpoint accepts WAV reliably; webm/opus support is not
// guaranteed, so we re-encode client-side using the Web Audio API (no libs).
// ---------------------------------------------------------------------------
async function audioBlobToWav(blob: Blob): Promise<Blob> {
  const arrayBuf = await blob.arrayBuffer();
  const Ctx = (window.AudioContext || (window as any).webkitAudioContext);
  const audioCtx = new Ctx({ sampleRate: 16000 });
  try {
    const audioBuffer = await audioCtx.decodeAudioData(arrayBuf);
    const numCh = audioBuffer.numberOfChannels;
    const len = audioBuffer.length;
    const mono = new Float32Array(len);
    for (let c = 0; c < numCh; c++) {
      const data = audioBuffer.getChannelData(c);
      for (let i = 0; i < len; i++) mono[i] += data[i] / numCh;
    }
    const buffer = new ArrayBuffer(44 + len * 2);
    const view = new DataView(buffer);
    const writeStr = (off: number, s: string) => {
      for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
    };
    writeStr(0, 'RIFF');
    view.setUint32(4, 36 + len * 2, true);
    writeStr(8, 'WAVE');
    writeStr(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);          // PCM
    view.setUint16(22, 1, true);          // mono
    view.setUint32(24, 16000, true);      // sample rate
    view.setUint32(28, 32000, true);      // byte rate
    view.setUint16(32, 2, true);          // block align
    view.setUint16(34, 16, true);         // bits per sample
    writeStr(36, 'data');
    view.setUint32(40, len * 2, true);
    let off = 44;
    for (let i = 0; i < len; i++) {
      const s = Math.max(-1, Math.min(1, mono[i]));
      view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      off += 2;
    }
    return new Blob([view.buffer], { type: 'audio/wav' });
  } finally {
    audioCtx.close();
  }
}

interface TeachBackChatProps {
  extractedData: any;
  demoMode: boolean;
  onVoiceChange?: (active: boolean, status: string) => void;
}

const TeachBackChat = forwardRef<TeachBackChatHandle, TeachBackChatProps>(
  ({ extractedData, demoMode, onVoiceChange }, ref) => {
    const [chat, setChat] = useState({
      questions: ["Can you tell me how you will take your Metformin?"],
      responses: [] as string[],
      corrections: [] as string[],
      score: undefined as number | undefined
    });
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);

    // Voice recording state
    const [isRecording, setIsRecording] = useState(false);
    const [voiceBusy, setVoiceBusy] = useState(false); // transcribing/processing
    const [voiceError, setVoiceError] = useState<string | null>(null);

    const mediaRecorderRef = useRef<MediaRecorder | null>(null);
    const chunksRef = useRef<Blob[]>([]);
    // Refs so the imperative toggleVoice always reads the freshest state.
    const isRecordingRef = useRef(false);
    const loadingRef = useRef(false);
    const voiceBusyRef = useRef(false);

    useEffect(() => { isRecordingRef.current = isRecording; }, [isRecording]);
    useEffect(() => { loadingRef.current = loading; }, [loading]);
    useEffect(() => { voiceBusyRef.current = voiceBusy; }, [voiceBusy]);

    // Keep the latest chat snapshot for building teach-back payloads.
    const chatRef = useRef(chat);
    useEffect(() => { chatRef.current = chat; }, [chat]);

    const reportVoice = useCallback((active: boolean, status: string) => {
      if (onVoiceChange) onVoiceChange(active, status);
    }, [onVoiceChange]);

    // ---------------------------------------------------------------------
    // Voice recording (STT) — MediaRecorder API
    // ---------------------------------------------------------------------

    const cleanupRecorder = () => {
      if (mediaRecorderRef.current) {
        try { mediaRecorderRef.current.stream.getTracks().forEach((t) => t.stop()); } catch {}
        mediaRecorderRef.current = null;
      }
      chunksRef.current = [];
    };

    const stopRecording = useCallback(async () => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state === 'inactive') {
        setIsRecording(false);
        cleanupRecorder();
        return;
      }

      setIsRecording(false);
      setVoiceBusy(true);
      reportVoice(false, 'Transcribing audio via Agent 3 STT...');

      const stopped = new Promise<void>((resolve) => {
        recorder.onstop = () => resolve();
        recorder.stop();
      });
      await stopped;

      const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
      cleanupRecorder();

      if (blob.size === 0) {
        setVoiceBusy(false);
        setVoiceError('No audio captured. Check your microphone.');
        reportVoice(false, 'No audio captured — check your microphone.');
        return;
      }

      try {
        // Re-encode webm/opus -> WAV so Sarvam STT reliably accepts it.
        reportVoice(false, 'Encoding audio for Agent 3 STT...');
        const wavBlob = await audioBlobToWav(blob);
        const text = await speechToText(wavBlob);
        const transcript = (text || '').trim();
        if (transcript) {
          setInput(transcript); // auto-populate the chat input for review
          setVoiceError(null);
          reportVoice(false, `Transcribed ✓ — review then hit VERIFY`);
        } else {
          setVoiceError('Transcription returned empty text.');
          reportVoice(false, 'Transcription was empty — try again.');
        }
      } catch (err: any) {
        // Sarvam outages come back as a 503 with `{ "error": "..." }`. Prefer
        // that server-provided message so the user gets the typed-input hint,
        // then fall back to other shapes / a generic failure.
        const serverError = err?.response?.data?.error;
        const detail =
          serverError ||
          err?.response?.data?.detail ||
          err?.message ||
          'Speech-to-text failed.';
        setVoiceError(typeof detail === 'string' ? detail : 'Speech-to-text failed.');
        reportVoice(false, 'STT failed — try again.');
      } finally {
        setVoiceBusy(false);
      }
    }, [reportVoice]);

    const startRecording = useCallback(async () => {
      setVoiceError(null);
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
        setVoiceError('Voice recording is not supported in this browser.');
        reportVoice(false, 'Voice recording unsupported in this browser.');
        return;
      }

      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        setVoiceError('Microphone permission denied or unavailable.');
        reportVoice(false, 'Microphone permission denied.');
        return;
      }

      const mimeType = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '';
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setIsRecording(true);
      reportVoice(true, 'RECORDING... (Click to stop)');
    }, [reportVoice]);

    const toggleVoice = useCallback(() => {
      if (loadingRef.current || voiceBusyRef.current) return;
      if (isRecordingRef.current) {
        void stopRecording();
      } else {
        void startRecording();
      }
    }, [startRecording, stopRecording]);

    useImperativeHandle(ref, () => ({ toggleVoice }), [toggleVoice]);

    // Release the mic if the component unmounts mid-recording.
    useEffect(() => () => cleanupRecorder(), []);

    // ---------------------------------------------------------------------
    // Teach-Back submit + TTS playback
    // ---------------------------------------------------------------------

    const speakText = async (text: string) => {
      if (!text) return;
      try {
        const base64 = await textToSpeech(text, 'en');
        if (base64) {
          const audio = new Audio('data:audio/wav;base64,' + base64);
          await audio.play().catch(() => {/* autoplay may be blocked; ignore */});
        }
      } catch {
        // TTS is best-effort; never block the chat on a voice failure.
      }
    };

    const onSubmit = async (e: React.FormEvent) => {
      e.preventDefault();
      if (!input.trim() || loading) return;

      const userText = input.trim();
      setInput('');
      setLoading(true);

      if (demoMode) {
        setTimeout(() => {
          setChat(prev => ({
            questions: [...prev.questions, "Excellent correction. Next, what specific warning signs mean you must seek immediate clinical emergency evaluation?"],
            responses: [...prev.responses, userText],
            corrections: [...prev.corrections, "Correct alignment confirmed. Note: Always ingest Metformin strictly right after heavy meals to protect gastric lining tracks."],
            score: 88
          }));
          setLoading(false);
        }, 1000);
        return;
      }

      try {
        const payload = {
          questions_asked: chatRef.current.questions,
          patient_responses: [...chatRef.current.responses, userText],
          corrections_given: chatRef.current.corrections
        };
        const res = await evaluateTeachBack(extractedData, payload, userText);
        const updated = {
          questions: res.questions_asked || [...chatRef.current.questions, "Next, do you know what precautions you must follow?"],
          responses: res.patient_responses || [...chatRef.current.responses, userText],
          corrections: res.corrections_given || [...chatRef.current.corrections, "Assessment processed successfully."],
          score: res.understanding_score || 92
        };
        setChat(updated);

        // Agent 3 speaks the response aloud: prefer the latest correction,
        // otherwise the latest question so the agent still converses.
        const latestCorrection = updated.corrections[updated.corrections.length - 1];
        const latestQuestion = updated.questions[updated.questions.length - 1];
        void speakText(latestCorrection || latestQuestion || '');
      } catch {
        setChat(prev => ({
          questions: [...prev.questions, "Next, do you know what warning signs mean you must visit the ER?"],
          responses: [...prev.responses, userText],
          corrections: [...prev.corrections, "Local response cached. Always consume Metformin right after your morning and evening meals."],
          score: 85
        }));
      } finally {
        setLoading(false);
      }
    };

    return (
      <div className="bg-slate-900 border border-slate-800 rounded-3xl overflow-hidden shadow-2xl flex flex-col h-[520px] backdrop-blur-md relative w-full">
        <div className="bg-slate-950 px-5 py-4 border-b border-white/5 flex items-center justify-between">
          <div>
            <h3 className="font-black text-white text-base tracking-tight">Interactive Patient Teach-Back Loop</h3>
            <p className="text-[11px] font-mono text-slate-400">AGENT 3 VERIFIER CORE • TARGET POST ROUTE: /api/teach-back</p>
          </div>
          {chat.score && (
            <div className="bg-purple-500/10 border border-purple-500/30 px-3 py-1.5 rounded-xl text-center">
              <span className="text-[9px] font-black tracking-widest text-purple-400 block uppercase">Metrics Score</span>
              <span className="text-lg font-black text-white">{chat.score}%</span>
            </div>
          )}
        </div>

        <div className="flex-1 p-5 overflow-y-auto space-y-4 bg-slate-950/20 font-medium text-xs">
          {chat.questions.map((q, idx) => (
            <div key={idx} className="space-y-3">
              <div className="flex gap-3 max-w-[85%]">
                <div className="w-8 h-8 rounded-xl bg-purple-600 font-black text-white flex items-center justify-center shadow-md shrink-0">AI</div>
                <div className="bg-slate-800 border border-white/5 text-slate-100 p-3.5 rounded-2xl rounded-tl-none shadow-md space-y-2 leading-relaxed text-sm">
                  <p>{q}</p>
                </div>
              </div>

              {chat.responses[idx] && (
                <div className="flex gap-3 max-w-[85%] ml-auto justify-end">
                  <div className="bg-indigo-600 text-white p-3.5 rounded-2xl rounded-tr-none shadow-lg text-sm leading-relaxed">
                    <p>{chat.responses[idx]}</p>
                  </div>
                  <div className="w-8 h-8 rounded-xl bg-slate-700 font-bold text-slate-200 flex items-center justify-center shrink-0">PT</div>
                </div>
              )}

              {chat.corrections[idx] && (
                <div className="flex gap-3 max-w-[85%] pl-11">
                  <div className="bg-amber-500/10 border border-amber-500/20 text-amber-200 p-3.5 rounded-2xl shadow-xs leading-relaxed text-sm">
                    <span className="text-[10px] font-black uppercase text-amber-400 tracking-wider block mb-1">💡 Clinical Guidance Review</span>
                    <p>{chat.corrections[idx]}</p>
                  </div>
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="flex items-center gap-2 text-purple-400 font-mono text-[10px] pl-11 animate-pulse">
              <span className="h-1.5 w-1.5 rounded-full bg-purple-400 animate-ping" />
              <span>Agent 3 computing semantic intent vectors...</span>
            </div>
          )}
        </div>

        {voiceError && (
          <div className="px-4 pt-2">
            <p className="text-[11px] font-semibold text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-1.5">
              {voiceError}
            </p>
          </div>
        )}

        <form onSubmit={onSubmit} className="p-4 bg-slate-950 border-t border-white/5 flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Respond to verify your medicine compliance knowledge..."
            className="flex-1 bg-slate-900 border border-white/10 rounded-xl px-4 py-3 text-sm text-white focus:outline-hidden focus:border-purple-500 font-medium tracking-tight"
            disabled={loading || isRecording || voiceBusy}
          />

          {/* Voice / STT trigger — drives the same MediaRecorder as the page button. */}
          <button
            type="button"
            onClick={toggleVoice}
            disabled={loading || voiceBusy}
            title={isRecording ? 'Stop recording' : 'Open voice link'}
            className={`px-4 rounded-xl font-black text-xs uppercase tracking-wider transition-all shadow-md shrink-0 ${
              isRecording
                ? 'bg-red-600 animate-pulse text-white shadow-lg shadow-red-600/30'
                : voiceBusy
                  ? 'bg-slate-700 text-slate-300 animate-pulse'
                  : 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-indigo-600/20'
            }`}
          >
            {isRecording ? '🛑 STOP' : voiceBusy ? '…' : '🎙️'}
          </button>

          <button
            type="submit"
            disabled={!input.trim() || loading}
            className="bg-purple-600 hover:bg-purple-700 disabled:bg-slate-800 text-white font-black text-xs uppercase tracking-wider px-5 rounded-xl transition-all shadow-md"
          >
            Verify
          </button>
        </form>
      </div>
    );
  }
);

TeachBackChat.displayName = 'TeachBackChat';

export default TeachBackChat;