# MedGuardian

MedGuardian is a multi-agent AI companion for post-discharge patient care. It is designed to help patients understand the information written on their discharge papers, especially after leaving the hospital when they are tired, stressed, and trying to remember many instructions at once.

This project combines a FastAPI backend, a Next.js frontend, and multiple AI-driven agents into one experience that can interpret medical documents, check for safety concerns, explain information in plain language, and verify whether the patient actually understands the plan.

---

## What this project is about

A discharge paper is often long, dense, and filled with medical terms. Many patients leave the hospital with a document that includes:
- diagnosis information,
- medication instructions,
- warning signs to monitor,
- follow-up dates,
- precautions and care steps.

The problem is that these papers are frequently hard to understand in the moment. Patients may forget what to do, misunderstand dosage instructions, or miss important warning signs. MedGuardian aims to solve that by acting like a digital discharge companion that can interpret the document and make the information easier to understand, safer to follow, and more actionable.

In simple terms, MedGuardian turns a confusing discharge paper into a clearer, guided, and safer experience.

---

## The full product idea

The product is built around the idea of a healthcare assistant that works like an intelligent post-discharge support system.

It is meant to help a patient by:
1. receiving or reading a discharge document,
2. extracting key information from it,
3. spotting safety issues such as interactions or duplicate medications,
4. explaining the instructions in plain language,
5. checking whether the patient truly understood the plan,
6. guiding them with follow-up support and escalation logic when needed.

This is why the project has both a frontend experience and a backend orchestration layer. The frontend makes the product usable and approachable, while the backend handles the logic, agent coordination, and data processing.

---

## Architecture overview

### Frontend
The frontend is a Next.js web app built with React and TypeScript. It presents the experience to the user through polished pages, authentication views, a portal experience, and a product story that explains the purpose of the system.

The frontend includes:
- a landing/home experience,
- an about page,
- a why-us page,
- an agents page,
- login/signup pages,
- a patient-facing portal experience,
- reusable UI components and layout pieces.

It uses:
- Next.js App Router
- React 19
- TypeScript
- Tailwind CSS for utility styling
- Framer Motion for animation
- Lucide React for icons
- Axios for API requests
- clsx and tailwind-merge for flexible styling utilities

The visual style is intentionally calm, accessible, and healthcare-friendly, with soft neutrals, teal accents, and a clear information hierarchy.

### Backend
The backend is a FastAPI service that exposes API endpoints for the frontend and coordinates the internal agents. It handles document upload, safety checks, teach-back conversations, and the orchestration flow between the different agents.

The backend is organized into modules such as:
- app/api for routes and endpoints,
- app/agents for specialized AI logic,
- app/services for integrations and processing helpers,
- app/db for persistence helpers,
- app/core for shared configuration and exceptions,
- app/models and app/schemas for structured data contracts.

### AI agents
The core intelligence of the system lives in the agent layer. The project is designed around multiple agents with distinct responsibilities:
- Document Intelligence: extracts structured information from discharge paperwork.
- Safety Cross-Check: evaluates drug interactions, duplicates, and other safety concerns.
- Teach-Back Verification: checks how well the patient understands the instructions.
- Adherence Follow-Up: supports reminders and follow-up logic in Phase 1 mock form.
- Symptom Escalation: handles escalation logic for warning signs from the discharge paper.

The system is designed so each agent can be developed and improved independently while still following a shared contract.

---

## What happens when a user uses the product

A typical flow looks like this:

1. A patient uploads or interacts with a discharge document.
2. The document intelligence agent extracts important medical details.
3. The safety agent scans the content for risks.
4. The system explains the instructions in plain language.
5. The teach-back agent asks the patient to confirm understanding.
6. The experience guides the patient through recovery with clearer, safer instructions.

This is the heart of the application: it takes a complex discharge paper and turns it into a more understandable and useful support experience.

---

## Repository structure

```text
backend/
  app/
    agents/
    api/
    core/
    db/
    models/
    schemas/
    services/
  requirements.txt
  main.py

frontend/
  app/
    about/
    admin/
    agents/
    assistant/
    login/
    signup/
    why-us/
  Components/
  Services/
  types/
  package.json

context.md
claude.md
README.md
```

---

## Installed packages and dependencies

### Backend packages
The backend uses a wide range of Python packages, including:
- fastapi
- pydantic
- uvicorn
- python-dotenv
- python-multipart
- pandas
- numpy
- anthropic
- openai
- supabase
- twilio
- requests
- httpx
- aiohttp
- python-dateutil
- PyYAML
- Pillow

These are installed through the backend requirements file:

```bash
cd backend
pip install -r requirements.txt
```

### Frontend packages
The frontend uses these main JavaScript and TypeScript packages:
- next
- react
- react-dom
- typescript
- tailwindcss
- @tailwindcss/postcss
- framer-motion
- lucide-react
- axios
- clsx
- tailwind-merge
- eslint
- eslint-config-next
- @types/react
- @types/react-dom
- @types/node

These are installed with:

```bash
cd frontend
npm install
```

### Why these packages matter
- Tailwind CSS gives the app a responsive, modern design system.
- Framer Motion helps create smooth transitions and animated UI sections.
- Lucide React provides the visual icons throughout the experience.
- Axios is used for API requests from the frontend to the backend.
- Next.js powers routing, rendering, and app structure.
- FastAPI and Pydantic provide a strong Python backend foundation.
- Supabase, OpenAI, Anthropic, and Twilio-related packages suggest the app is designed to support cloud services and communication workflows.

---

## Backend details

### Main application entry
The backend entry point is defined in the main application file. It initializes the FastAPI app and exposes the service to the frontend.

### API layer
The app/api folder contains routers for:
- authentication,
- patients,
- safety checks,
- document upload,
- voice interactions,
- teach-back workflows,
- health checks.

These routers are where client requests are received and transformed into structured actions.

### Agent layer
The app/agents folder contains the logic for specialized agents. These modules are responsible for understanding discharge content, cross-checking safety issues, and helping the system provide reliable explanations.

### Services layer
The app/services folder holds the processing and integration code used by the agents and API routes. This could include AI service calls, document parsing, data transformation, or external API communication.

### Database and core modules
The app/db and app/core folders provide persistence helpers, shared configuration, and exception handling. These modules make it easier to evolve the system as it grows.

---

## Frontend details

### App pages
The app folder contains the main website structure, including:
- home page
- about page
- why-us page
- login and signup pages
- agents overview
- assistant experience
- admin and portal-related routes

### Components
The Components folder includes reusable UI building blocks for:
- navigation,
- hero sections,
- storytelling sections,
- portal features,
- auth layout,
- shared cards, buttons, alerts, badges, and input fields.

### Services and types
The Services folder contains frontend API clients that communicate with the backend. The types folder contains shared TypeScript models that define the shape of messages, patients, and other data contracts.

---

## Security and privacy considerations

This project is healthcare-oriented, which means safety and privacy matter deeply.

The current implementation is designed with the following principles in mind:
- patient data should be handled with care,
- sensitive information should not be exposed casually,
- safety-critical recommendations should be validated,
- the system should be cautious and transparent,
- real-world deployments should add stronger authentication and storage protection.

The project also includes a privacy-first approach in the product story and architecture ideas, with secure storage and authentication patterns in mind.

---

## How to run the project locally

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Expected local URLs
- Frontend: http://localhost:3000
- Backend: http://localhost:8000

---

## Why the discharge paper matters

The discharge paper is the central artifact in this project. It contains the summary of care that the patient needs to follow after leaving the hospital. That document may include medication schedules, follow-up appointments, warning signs, and special instructions. If the patient does not understand it clearly, the risk of confusion, non-adherence, or mistakes increases.

MedGuardian exists to reduce that burden by making the discharge paper more understandable and easier to act on.

---

## Development notes

- The frontend uses the App Router pattern in Next.js.
- The backend uses FastAPI and Pydantic for structured contracts.
- The project is built modularly, so agents, routes, services, and UI can evolve independently.
- The shared contract described in context.md should be preserved when changing backend data structures.
- The project is still evolving, and some flows are currently mocked for Phase 1 while the core functionality is being built out.

---

## Suggested next steps

- connect the full document extraction pipeline end-to-end,
- integrate real safety analysis with live data sources,
- strengthen authentication and secure storage,
- expand teach-back and escalation workflows,
- improve accessibility, mobile experience, and real-world reliability.

---

## Summary

MedGuardian is a healthcare-focused AI product that takes the information on a discharge paper and transforms it into a safer, clearer, and more supportive experience for the patient. It combines a modern frontend, a structured Python backend, multiple AI agents, and strong design principles to make post-discharge care easier to understand and follow.
