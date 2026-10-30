# HAS AI STUDIO | Control Center

**HAS-AI-TEAM** is an advanced, localized, multi-agent artificial intelligence orchestration studio. It provides a web-based dashboard for managing AI workflows, creating complex project pipelines, and assigning specialized roles to various LLM (Large Language Model) agents working in parallel or sequential chains.

Powered primarily by local AI models via **Ollama**, this system consists of a central Orchestrator, autonomous Agent Workers, a real-time Angular-based Web CLI interface, and an overarching TeamLead agent capable of designing project structures before execution.

## 🚀 Key Features

- **Angular Web CLI Dashboard**: A modern, sleek control center built with **Angular 18+** and **Tailwind CSS**.
- **Universal Scaffolding Engine**: A completely framework-agnostic system. Supports setting up any tech stack (Django, .NET, Node, Rust, Flutter, etc.) purely through agent-generated, non-interactive CLI commands.
- **Cross-Agent Technical Handover**: Advanced collaboration protocol where agents (Backend, DevOps, etc.) leave detailed technical notes that are automatically injected as prioritized context for subsequent agents.
- **Automated Model Management**: The system automatically detects missing models (e.g., `llama3.1:latest`) on startup and triggers an asynchronous background pull via Ollama, ensuring zero-configuration readiness.
- **Agent-Led Provisioning (ALP)**: The TeamLead agent possesses "Provisioner" authority. It intelligently detects missing SDKs or compilers, autonomously installs them (e.g., via `apt-get`), and verifies the environment before writing code.
- **Persistent SDK Caching**: Heavy SDKs (Flutter, Java, Android SDK) installed by agents are cached in a dedicated Docker volume (`/opt/sdks`). The backend dynamically scans and appends these tools to the system `PATH` for subsequent zero-download project creations.
- **Real-Time Monitoring**: Live CPU, RAM, Disk, and dedicated **Neon GPU Utilization** tracking leveraging `pynvml`.
- **Role-Based AI Agents**: Specialized agents (`TeamLead`, `Frontend`, `Backend`, `Tester`, `Security`) with unique neon-styled status indicators.
- **Dynamic Orchestration**: Jobs are locked, processed, and tracked in an SQLite-backed queue (`data/traceability.db`).

---

## 🏗 System Architecture

For a visual breakdown of the multi-agent control center, container networking, and data flows, see the [Architecture Diagram](docs/architecture-diagram.html).

The project consists of several independent modules:

- **`core/`**: FastAPI Orchestrator managing the database, job queue, global locking, and Socket.IO real-time emissions.
- **`client/`**: Modern Angular frontend providing the user interface, real-time services, and reactive state management.
- **`prompts/`**: Structured markdown persona definitions for each agent role (Backend, Frontend, DevOps, etc.).
- **`apps/`**: Output directory where agents write code and project structure.
- **`workspace/`**: Agent-specific workspace where technical reports and handover notes are stored.

---

## 📦 Installation & Setup

### Prerequisites
- [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/)
- Modern Web Browser
- **NVIDIA GPU** (Optional but recommended): Ensure `nvidia-container-toolkit` is installed on the host for GPU monitoring and acceleration.

### Quick Start

1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd has-ai-team
   ```

2. **Start the environment:**
   ```bash
   docker compose up -d --build
   ```
   *This initializes the Ollama server, FastAPI Orchestrator, Agent Workers, and the Angular Web CLI.*

3. **Access the Dashboard:**
   Open `http://localhost:4200` in your browser.

---

## ⚙️ Configuration

Control center settings are manageable via the **Settings** tab or `data/config.json`:
- **LLM Provider**: Toggle between Local `Ollama` or OpenAI Compatible endpoints.
- **Models**: Dynamically pull and assign models directly from the UI.
- **System Status**: Real-time tracking of model installation status and hardware health.

---

## 🛡 Tech Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy (SQLite), Socket.IO, pynvml
- **Frontend:** Angular 18, Tailwind CSS, Heroicons, Lucide
- **Infrastructure:** Docker, Nginx, NVIDIA Container Runtime

---

## 📄 License
This system is developed for the **HAS AI STUDIO**. All rights reserved.

---
**Developed by** [@fathasss](https://github.com/fathasss)
