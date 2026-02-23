# HAS AI STUDIO | Control Center

**HAS-AI-TEAM** is an advanced, localized, multi-agent artificial intelligence orchestration studio. It provides a web-based dashboard for managing AI workflows, creating complex project pipelines, and assigning specialized roles to various LLM (Large Language Model) agents working in parallel or sequential chains.

Powered primarily by local AI models via **Ollama**, this system consists of a central Orchestrator, autonomous Agent Workers, a real-time Angular-based Web CLI interface, and an overarching TeamLead agent capable of designing project structures before execution.

## 🚀 Key Features

- **Angular Web CLI Dashboard**: A modern, sleek control center built with **Angular 18+** and **Tailwind CSS**.
- **Real-Time Monitoring**:
    - **System Metrics**: Live CPU, RAM, and Disk usage updates.
    - **GPU Monitoring**: Dedicated **Neon GPU Utilization** tracking leveraging `pynvml` and NVIDIA Docker support.
- **Role-Based AI Agents**: Specialized agents (`TeamLead`, `Frontend`, `Backend`, `Tester`, `Security`) with unique neon-styled status indicators (**WORKING**, **AVAIL**, **DOWN**).
- **Expandable Trace Logs**: Smart log management that collapses long JSON outputs with a gradient fade, allowing for a cleaner UI while keeping detailed traces accessible via a single click.
- **Dynamic Orchestration**: Jobs are locked, processed, and tracked in an SQLite-backed queue (`data/traceability.db`).
- **Pipeline Workflow Visualization**: A visual pipeline sequence at the bottom of the active projects view to track the execution steps in real-time.
- **Containerized Architecture**: Fully orchestrated via Docker-Compose with integrated NVIDIA GPU runtime support.

---

## 🏗 System Architecture

The project consists of several independent modules:

- **`core/`**: FastAPI Orchestrator (`main.py`) managing the database, job queue, global locking, and Socket.IO real-time emissions.
- **`client/`**: Modern Angular frontend providing the user interface, real-time services, and reactive state management.
- **`prompts/`**: Structured JSON persona definitions for each agent role.
- **`apps/`**: Output directory where agents write code and project structure.
- **`docker/`**: Optimized Dockerfiles for building the production-ready containers.

---

## 📦 Installation & Setup

### Prerequisites
- [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docs.com/compose/)
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
   Open `http://localhost:4000` in your browser.

---

## ⚙️ Configuration

Control center settings are manageable via the **Settings** tab or `data/config.json`:
- **LLM Provider**: Toggle between Local `Ollama` or OpenAI Compatible endpoints.
- **Models**: Dynamically pull and assign models directly from the UI.
- **System Limits**: Configure timeout and concurrency settings for heavy LLM operations.

---

## 🛡 Tech Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy, Socket.IO, pynvml
- **Frontend:** Angular 18, Tailwind CSS, Heroicons, Lucide
- **Database:** SQLite (Traces & Jobs)
- **Infrastructure:** Docker, Nginx, NVIDIA Container Runtime

---

## 📄 License
This system is developed for the **HAS AI STUDIO**. All rights reserved.

---
**Developed by** [@fathasss](https://github.com/fathasss)
