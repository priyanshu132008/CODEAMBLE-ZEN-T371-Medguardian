// test_integration.js — MedGuardian frontend<->backend bridge verification.
// Hits the live FastAPI backend the way the Next.js frontend does, verifies CORS,
// and validates that both core endpoints return the exact JSON contract from
// context.md. Run with: node test_integration.js (Node 18+ for global fetch).

const BASE = 'http://localhost:8000/api';
const ORIGIN = 'http://localhost:3000'; // the Next.js dev origin

const RED = '\x1b[31m', GREEN = '\x1b[32m', YELLOW = '\x1b[33m', CYAN = '\x1b[36m', BOLD = '\x1b[1m', RESET = '\x1b[0m';

let failures = 0;
const check = (label, ok, detail = '') => {
  const mark = ok ? `${GREEN}✓${RESET}` : `${RED}✗${RESET}`;
  console.log(`  ${mark} ${label}${detail ? ` ${YELLOW}${detail}${RESET}` : ''}`);
  if (!ok) failures++;
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function fetchJson(path, { method = 'POST', body, headers } = {}) {
  const init = { method, headers: { 'Content-Type': 'application/json', Origin: ORIGIN, ...(headers || {}) } };
  if (body) init.body = JSON.stringify(body);
  const res = await fetch(BASE + path, init);
  let data = null;
  const text = await res.text();
  try { data = text ? JSON.parse(text) : null; } catch { /* keep text */ }
  return { ok: res.ok, status: res.status, headers: res.headers, data, text };
}

async function checkCorsPreflight() {
  console.log(`\n${BOLD}${CYAN}[1/3] CORS preflight (OPTIONS /api/safety-check)${RESET}`);
  try {
    const res = await fetch(BASE + '/safety-check', {
      method: 'OPTIONS',
      headers: {
        Origin: ORIGIN,
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type',
      },
    });
    const acao = res.headers.get('access-control-allow-origin');
    const acam = res.headers.get('access-control-allow-methods');
    const acah = res.headers.get('access-control-allow-headers');
    check(`OPTIONS reachable (HTTP 200/204)`, res.ok || res.status === 204, `(got ${res.status})`);
    check(`Access-Control-Allow-Origin present`, !!acao, `→ ${acao}`);
    check(`Allow-Origin permits the Next.js origin`, acao === '*' || acao === ORIGIN, `→ ${acao}`);
    check(`Allow-Methods includes POST`, !!acam && /post/i.test(acam), `→ ${acam}`);
    check(`Allow-Headers includes content-type`, !!acah && /content-type/i.test(acah), `→ ${acah}`);
  } catch (e) {
    check('CORS preflight request', false, `(network error: ${e.message})`);
  }
}

async function checkSafety() {
  console.log(`\n${BOLD}${CYAN}[2/3] POST /api/safety-check (Agent 2)${RESET}`);
  const body = {
    medications: [
      { name: 'Metformin', dosage: '500mg', frequency: 'Twice daily after meals', duration: '90 days' },
      { name: 'Clopidogrel', dosage: '75mg', frequency: 'Once daily', duration: '30 days' },
      { name: 'Omeprazole', dosage: '40mg', frequency: 'Once daily', duration: '14 days' },
    ],
  };
  let r;
  try {
    r = await fetchJson('/safety-check', { body });
  } catch (e) {
    return check('safety-check request', false, `(network error: ${e.message})`);
  }
  check(`HTTP 200`, r.status === 200, `(got ${r.status})`);
  const acao = r.headers.get('access-control-allow-origin');
  check(`CORS Allow-Origin on real response`, !!acao && (acao === '*' || acao === ORIGIN), `→ ${acao}`);
  const flags = r.data && r.data.safety_flags;
  check(`response has 'safety_flags' array`, Array.isArray(flags));
  if (Array.isArray(flags) && flags.length) {
    const f = flags[0];
    check(`flag has 'type'`, typeof f.type === 'string', `→ ${f.type}`);
    check(`flag has 'medications_involved' array`, Array.isArray(f.medications_involved), `→ ${JSON.stringify(f.medications_involved)}`);
    check(`flag has 'severity'`, typeof f.severity === 'string', `→ ${f.severity}`);
    check(`flag has 'message'`, typeof f.message === 'string' && f.message.length > 0);
    check(`detected Clopidogrel+Omeprazole interaction`, /clopidogrel/i.test(JSON.stringify(f)) && /omeprazole/i.test(JSON.stringify(f)));
  } else {
    check(`safety_flags non-empty (interaction expected)`, false);
  }
}

async function checkTeachBack() {
  console.log(`\n${BOLD}${CYAN}[3/3] POST /api/teach-back (Agent 3, via OpenRouter ~8-15s)${RESET}`);
  const body = {
    extracted: {
      diagnosis: 'Type 2 Diabetes Mellitus',
      medications: [{ name: 'Metformin', dosage: '500mg', frequency: 'Twice daily after meals', duration: '90 days' }],
      precautions: ['Monitor blood sugar daily'],
      follow_up_date: '2026-08-15',
      warning_signs: ['Extreme dizziness'],
    },
    current_teach_back: {
      questions_asked: ['How will you take your Metformin?'],
      patient_responses: [],
      corrections_given: [],
    },
    patient_response: 'I will take it twice a day after meals',
  };
  let r;
  try {
    r = await fetchJson('/teach-back', { body });
  } catch (e) {
    return check('teach-back request', false, `(network error: ${e.message})`);
  }
  if (r.status === 429) {
    return check(`HTTP 200`, false, `(429 OpenRouter rate-limited — backend bridge OK, upstream busy. Retry in a moment.)`);
  }
  check(`HTTP 200`, r.status === 200, `(got ${r.status}${r.text ? `: ${r.text.slice(0,120)}` : ''})`);
  const tb = r.data;
  if (tb) {
    check(`'questions_asked' array`, Array.isArray(tb.questions_asked), `len=${(tb.questions_asked||[]).length}`);
    check(`'patient_responses' array`, Array.isArray(tb.patient_responses));
    check(`'understanding_score' number`, typeof tb.understanding_score === 'number', `→ ${tb.understanding_score}`);
    check(`'corrections_given' array`, Array.isArray(tb.corrections_given));
  }
}

(async () => {
  console.log(`${BOLD}MedGuardian bridge verification → ${BASE}${RESET}`);
  // Liveness probe
  try {
    const probe = await fetch(BASE + '/safety-check', {
      method: 'OPTIONS',
      headers: { Origin: ORIGIN, 'Access-Control-Request-Method': 'POST' },
    }).catch(() => null);
    if (!probe) throw new Error('backend not reachable');
  } catch (e) {
    console.log(`\n${RED}${BOLD}Backend is not running on ${BASE}.${RESET}`);
    console.log(`${YELLOW}Start it: cd backend && source venv/bin/activate && uvicorn main:app --port 8000${RESET}`);
    process.exit(1);
  }

  await checkCorsPreflight();
  await checkSafety();
  await checkTeachBack();

  console.log('\n' + (failures === 0
    ? `${BOLD}${GREEN}BRIDGE SECURE — 0 failures. Frontend and backend communicate with correct CORS and contract shapes.${RESET}`
    : `${BOLD}${RED}${failures} check(s) FAILED.${RESET}`));
  process.exit(failures === 0 ? 0 : 1);
})();