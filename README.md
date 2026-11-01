# 🏢 HAS AI STUDIO | Autonomous Multi-Agent Software Engineering Studio

[![Architecture](https://img.shields.io/badge/Architecture-Claw3D%20%7C%20FastAPI%20%7C%20Angular18-cyan.svg)](docs/architecture-diagram.html)
[![Inference](https://img.shields.io/badge/LLM%20Engine-Dual--Engine%20(Ollama%20+%20Cloud)-purple.svg)](#-dual-engine-llm-routing)
[![Memory](https://img.shields.io/badge/Memory-Cumulative%20Project%20Memory-gold.svg)](#-accumulated-project-memory-engine)
[![i18n](https://img.shields.io/badge/Languages-TR%20%7C%20EN%20(Bilingual)-blue.svg)](#-bilingual-multi-language-support-tren)
[![Testing](https://img.shields.io/badge/Testing-Live%20Synthetic%20E2E-emerald.svg)](#-live-synthetic-testing--verification)

**HAS AI STUDIO** is an advanced, localized, autonomous multi-agent software engineering studio. It provides a real-time **3D WebGL Virtual Office** where 8 specialized artificial intelligence agents collaborate, design architectures, write code, run live synthetic tests, and build complete software applications.

Powered by a **Dual-Engine LLM Architecture**, the system intelligently routes informal peer conversations to zero-cost local models (**Ollama**) while directing mission-critical planning and coding tasks to high-reasoning cloud or local LLMs (**Google Gemini 2.0 Flash/Pro**, **OpenAI GPT-4o**, **Anthropic Claude 3.5 Sonnet**).

<p align="center">
  <img src="docs/screenshots/office-3d-preview.jpg" alt="HAS AI Studio - 3D Autonomous AI Virtual Office" width="100%" />
</p>

---

## 🌟 Architectural Overview

```mermaid
flowchart TD
    subgraph UI["Web Studio (Angular 18 & Three.js :4200)"]
        Canvas["3D Isometric Virtual Office\n(8 Voxel Agents, Human-like Waypoint Walking, Group Circle/Facing Formations)"]
        TopBar["Unified Glass Topbar\n(Language Switcher TR/EN, Mission Dropdown, 3D Camera Modes)"]
        PhaseHUD["Ultra-Compact Floating Phase HUD\n(Non-intrusive Pill Bar & Collapsible Milestone Overlay)"]
        Drawer["560px Wide Agent Detail Drawer\n(Tasks, Chat, Project Memory, Synthetic Tests, AI Model)"]
    end

    subgraph Core["FastAPI Orchestrator (:8000)"]
        PhaseService["Dynamic Milestone Phasing Engine\n(phases/ROADMAP.md & PHASE_X.md)"]
        MemoryService["Memory Service\n(memory/PROJECT_MEMORY.md & {agent}_memory.md)"]
        UnifiedLLM["Unified LLM Router\n(Dual-Engine Local/Cloud Fallback)"]
        LiveTester["Live Synthetic Tester Engine\n(Socket.IO Real-time Stream)"]
        GlobalLock["Distributed Atomic Queue & SQLite WAL"]
    end

    subgraph Workers["Autonomous Agent Worker Container"]
        WorkerService["Worker Task Processor\n(Context & Memory Injection)"]
        UniversalScaffold["Universal CLI Scaffolder & Provisioner"]
        CodeExtractor["Code Extractor & Handover Synthesizer"]
    end

    subgraph Engines["Inference Layer"]
        Ollama["Local Ollama Container\n(Zero-Cost Realtime Peer Banter)"]
        CloudLLM["Cloud LLMs\n(Gemini 2.0, GPT-4o, Claude 3.5 Sonnet)"]
    end

    UI <-->|Socket.IO & REST| Core
    Core <-->|Queue & Handover| Workers
    Core -->|Idle Banter| Ollama
    Workers -->|Task Inference| CloudLLM
    Workers -->|Local Inference| Ollama
    Workers -->|Save Deliverables| FS["phases/ & memory/ & apps/"]
```

---

## 🚀 Key Capabilities

### 1. 🏢 Interactive 3D AI Virtual Office
- **Three.js WebGL Viewport**: High-performance 3D isometric studio running directly in the browser with full-bleed responsive layout.
- **8 Dedicated Voxel Agents**: Complete with personalized 3D models, neon accent rings, dynamic walking animations, and animated workstations.
- **Human-Like Waypoint Walking & Social Interactions**: Agents wander smoothly across waypoints, relax on the lounge sofa, grab espresso, chat at the water cooler, brainstorm at the glass whiteboard, or play retro arcade games.
- **Conversational Formations**: When 2 agents converse, they automatically position themselves face-to-face ($1.4\text{ m}$ distance). When 3 agents converse, they form an equilateral circle ($R = 0.95\text{ m}$, $120^\circ$ spacing) with inward angular orientation.
- **Multi-Perspective Camera Views**: Instant toggle between `3D ISO`, `SİNEMATİK` (dynamic low-angle), `KUŞBAKIŞI` (architectural top-down blueprint), `WAR ROOM` table focus, and `LOUNGE` focus.

### 2. 🌍 Bilingual Multi-Language Support (TR / EN)
- **Instant Reactive Language Switcher**: Sleek toggle pill in the top header (`[ 🇹🇷 TR | 🇬🇧 EN ]`).
- **Live UI Updates**: All navigation links, headers, tooltips, dialogs, status badges, and tabs update dynamically without page reloads.
- **Bilingual LLM Integration**:
  - TeamLead architectural consultation and preview plans adapt automatically to English or Turkish.
  - Multi-turn banter between agents automatically flows in natural English or Turkish based on user language preference.
  - Settings persisted in browser `localStorage`.

### 3. 🧠 Dual-Engine LLM Architecture
- **Informal Office Banter Engine**: Automatically routes social chit-chat and reciprocal peer dialogues to local Ollama (`llama3.1:latest`, `qwen2.5-coder:7b`) with zero token cost.
- **Task Execution Engine**: Routes code writing, sprint planning, and architectural synthesis to high-intelligence cloud LLMs (**Gemini 2.0 Flash / Pro**, **GPT-4o**, **Claude 3.5 Sonnet**) or dedicated local code models.
- **Per-Agent & Global Configuration**: Configure chat and task models globally or individually via the agent detail drawer (`⚙️ AI Modeli` tab) or `data/config.json`.

### 4. 📌 Project-Driven Multi-Agent Milestone Phasing
- **Interactive TeamLead Consultation**: Product Owners discuss requirements with TeamLead in Mission Hub. When the blueprint matures, TeamLead requests explicit user approval.
- **Work-Milestone Phasing (Not Rigid 1-Agent Ladders)**:
  - Milestone-driven collaboration where multiple agents work in tandem:
    - **Phase 1: Infrastructure & Data Architecture** (`@DevOps`, `@Database`)
    - **Phase 2: Business Logic & Web UI** (`@Backend`, `@Frontend`)
    - **Phase 3: Security, Synthetic Testing & Delivery** (`@Security`, `@Tester`, `@Documenter`, `@TeamLead`)
- **Ultra-Compact Floating Phase HUD**:
  - 38px floating glass pill bar displaying current phase, assigned agents, live progress bar, and TeamLead status. Expanding reveals non-intrusive floating milestone cards over the 3D scene.

### 5. 🗂️ Wide 560px Agent Detail Drawer
- Expanding an agent opens an ergonomic **560px** glass sliding drawer with 5 tabs:
  1. `📋 Work / Tasks`: Assigned tasks, current execution status, and file deliverables.
  2. `💬 Chat / Banter`: Real-time dialogue logs and agent social banter history.
  3. `🧠 Project Memory`: Agent's specialized memory notes and cross-phase architectural decisions.
  4. `🧪 Live Tests`: Real-time synthetic test run logs and step-by-step verification results.
  5. `⚙️ AI Engine`: Dual-Engine model switcher (Task LLM & Chat LLM independently selectable).

### 6. 🧠 Accumulated Project Memory Engine
- **Cross-Phase Collective Memory (`memory/`)**:
  - `memory/PROJECT_MEMORY.md`: Shared architectural decisions, API contracts, database schemas, and shared environment variables.
  - `memory/{agent}_memory.md`: Individual specialized memories (`teamlead_memory.md`, `backend_memory.md`, `frontend_memory.md`, etc.).
- **Automatic Context Injection**: When an agent begins a task, relevant project memory is pre-pended to the prompt.
- **Post-Task Memory Extraction**: Upon task completion, technical decisions and file paths are summarized and permanently saved to the project's memory repository.

### 7. 🧪 Live Synthetic End-to-End Testing & Verification
- Rather than running blind unit tests, the **Tester** agent executes synthetic user-journey test steps using `core/services/live_tester.py`.
- Each step streams live to the Web Studio via Socket.IO, displaying step name, pass/fail status, and execution duration in milliseconds.

---

## 👥 The 8 Specialized AI Agents

| Agent | Role | Accent Color | Primary Responsibilities |
|---|---|:---:|---|
| **TeamLead** | Solution Architect | `#facc15` (Gold) | Requirements elicitation, user approval gate, roadmap & milestone phase generation (`phases/`), memory synthesis. |
| **DevOps** | Infrastructure Engineer | `#f97316` (Orange) | Environment provisioning, Dockerfiles, Compose setups, CI/CD scripts, package manager setup. |
| **Database** | Data Architect | `#14b8a6` (Teal) | Schema modeling, ORM entity definitions, migrations, seeders, indexing strategies. |
| **Backend** | API Engineer | `#10b981` (Emerald) | REST / GraphQL / WebSocket endpoints, business logic, authentication, middleware, service layer. |
| **Frontend** | UI/UX Developer | `#06b6d4` (Cyan) | Component architecture, responsive layouts, client routing, state management, API integration. |
| **Security** | Security Auditor | `#ef4444` (Red) | OWASP vulnerability scans, CORS & auth token verification, input sanitation, secret shielding. |
| **Tester** | QA & Synthetic Tester | `#a855f7` (Purple) | Live synthetic user journey tests, contract validation, regression checks, test reporting. |
| **Documenter** | Technical Writer | `#38bdf8` (Sky Blue) | OpenAPI specs, README generation, architecture documentation, changelogs, deployment manuals. |

---

## 📁 Repository Structure

```
has-ai-studio/
├── apps/                         # Output directory for agent-generated codebases
├── client/                       # Angular 18+ Web Studio & Three.js 3D Office
│   ├── src/app/
│   │   ├── core/                 # Header, Sidebar, RightPanel, I18nService, TranslatePipe
│   │   ├── features/
│   │   │   ├── active-projects/  # 3D Three.js Office (Claw3D Scene, Floating HUD, 560px Drawer)
│   │   │   ├── dashboard/        # Mission Hub (TeamLead Architectural Station & Approval Flow)
│   │   │   ├── projects/         # Project & File Explorer with Syntax Highlighting
│   │   │   ├── reports/          # Team Sprint Reports & Handover Documents
│   │   │   ├── execution-traces/ # Raw Agent LLM Execution Log Replay & Diagnostics
│   │   │   └── settings/         # Node Registry, LLM Routing & Telemetry
│   │   └── services/             # Orchestrator API & Socket.IO Clients
├── core/                         # FastAPI Orchestration Engine
│   ├── routers/                  # API Endpoints (chat, sprint, jobs, llm, system, config)
│   ├── services/
│   │   ├── phase_service.py      # phases/ROADMAP.md & PHASE_X.md Milestone Management
│   │   ├── memory_service.py     # memory/PROJECT_MEMORY.md & Agent Memory State
│   │   ├── live_tester.py        # Live Synthetic Testing Engine
│   │   ├── unified_llm.py        # Dual-Engine Router (Ollama + Gemini/OpenAI/Claude)
│   │   └── worker_service.py     # Milestone Task Processor with Memory Injection
│   ├── config.py                 # System Configuration & Path Resolvers
│   ├── database.py               # SQLite WAL Engine & Session Management
│   └── schemas.py                # Pydantic Request/Response Models
├── data/                         # Persistent Storage (config.example.json, runtime db ignored)
├── docs/
│   └── architecture-diagram.html # Interactive Visual Architecture Diagram
├── memory/                       # Runtime Project Memory Storage
├── phases/                       # Project Phase Roadmaps & Specifications
├── prompts/                      # Specialized Persona Markdown Definitions
├── docker-compose.yml            # Multi-Container Deployment Specification
├── .env.example                  # Environment Variables Template (Secrets Shielded)
└── README.md                     # Studio Documentation
```

---

## 📦 Installation & Setup

### Prerequisites
- [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/) (v2.20+)
- Modern Web Browser with WebGL support (Chrome, Edge, Firefox, Brave)
- *(Optional)* NVIDIA GPU with `nvidia-container-toolkit` for local GPU-accelerated Ollama inference.

### Quick Start

1. **Clone the repository:**
   ```bash
   git clone https://github.com/fathasss/has-ai-studio.git
   cd has-ai-studio
   ```

2. **Configure Environment:**
   Copy the example environment file and configure settings:
   ```bash
   cp .env.example .env
   cp data/config.example.json data/config.json
   ```

3. **Configure Cloud LLM Keys (Optional for Cloud Tasks):**
   Set API keys in `.env` or configure them directly via the UI drawer:
   ```bash
   export GEMINI_API_KEY="your-gemini-key"
   # or
   export OPENAI_API_KEY="your-openai-key"
   ```

4. **Start the studio environment:**
   ```bash
   docker compose up -d --build
   ```
   *This starts:*
   - `has-ai-ollama`: Local model inference server (`:11434`)
   - `has-ai-orchestrator`: FastAPI central orchestrator (`:8000`)
   - `has-ai-agent-worker`: Autonomous worker container with CLI tools
   - `has-ai-web-cli`: Angular 18 Web Studio served via Nginx (`:4200`)

5. **Access the Studio:**
   Open `http://localhost:4200` in your browser.

---

## ⚙️ Dual-Engine LLM Configuration

| Context | Recommended Provider | Model | Notes |
|---|---|---|---|
| **Office Idle Banter** | **Ollama** (Local) | `llama3.1:latest` | Zero-cost continuous dialogue generation between wandering agents. |
| **Sprint Tasks / Code** | **Google Gemini** | `gemini-2.0-flash` | High-speed, high-reasoning code generation, and architectural design. |
| **Sprint Tasks / Code** | **OpenAI** | `gpt-4o` / `gpt-4o-mini` | Advanced multi-file reasoning and complex refactoring. |
| **Sprint Tasks / Code** | **Anthropic** | `claude-3-5-sonnet` | Exceptionally strong frontend and system-level coding. |
| **Offline Code Tasks** | **Ollama** (Local) | `qwen2.5-coder:7b` | Completely air-gapped, zero-cloud software engineering. |

Configurations can be customized per-agent or applied to the whole team in the **Agent Detail Drawer (`⚙️ AI Modeli`)** or via `data/config.json`.

---

## 🛡 Security & Privacy Shielding

- **No Secrets in Version Control**: `.env` and `data/config.json` are excluded via `.gitignore`. Templates (`.env.example` and `data/config.example.json`) are provided.
- **Air-Gapped Ready**: Operates 100% locally with Ollama without sending any data to external APIs if cloud providers are not configured.
- **Isolated Execution**: Workers run tasks within sandboxed Docker containers.

---

## 🛡 License & Credits

Developed with precision for the **HAS AI STUDIO**. All rights reserved.  
**Architect:** [@fathasss](https://github.com/fathasss)
