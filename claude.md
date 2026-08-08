# MedGuardian Project
A multi-agent AI companion for post-discharge patient care, built for CODEAMBLE 2026.
**CRITICAL: Read `context.md` before making any architectural or API decisions.**

## Build & Run Commands
- **Backend**: `cd backend && source venv/bin/activate && uvicorn main:app --reload --port 8000` (Windows: `venv\Scripts\activate`)
- **Frontend**: `cd frontend && npm run dev`
- **Install Python Deps**: `cd backend && pip install -r requirements.txt`
- **Install Node Deps**: `cd frontend && npm install`

## Coding Conventions & Constraints
- **Strict JSON Contract**: All backend agents MUST communicate using the exact JSON shape defined in `context.md`. Never invent new JSON keys or alter the schema.
- **Backend API**: Python, FastAPI, and Pydantic. Use Pydantic models strictly to enforce the JSON contract on all inputs and outputs.
- **Frontend**: Next.js App Router, Tailwind CSS, TypeScript, `lucide-react`. The UI must be clean, use soft blues/whites, and feature large typography designed for low-literacy/elderly accessibility.
- **Scope limitation**: Agents 4 (Adherence) and 5 (Escalation) are simulated mockups for Phase 1. Do not build real Twilio integrations yet.