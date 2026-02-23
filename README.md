# HAS AI STUDIO | Control Center

**HAS-AI-TEAM** is an advanced, localized, multi-agent artificial intelligence orchestration studio. It provides a web-based dashboard for managing AI workflows, creating complex project pipelines, and assigning specialized roles to various LLM (Large Language Model) agents working in parallel or sequential chains.

Powered primarily by local AI models via **Ollama**, this system consists of a central Orchestrator, autonomous Agent Workers, a real-time Web CLI interface, and an overarching TeamLead agent capable of designing project structures before execution.

## 🚀 Key Features

- **Web CLI Dashboard**: A modern, sleek control center interface (`index.html`) to interact with agents and monitor project sprints.
- **Role-Based AI Agents**: Pre-configured specialized agents (`TeamLead`, `Frontend`, `Backend`, `Tester`, `Security`) with distinct prompt behaviors and responsibilities.
- **Dynamic Orchestration**: Jobs are locked, processed, and tracked in an SQLite-backed queue (`data/traceability.db`).
- **Ollama Integration**: Fully integrated with Ollama for running models like LLaMA-3.1 locally. You can view, pull, and switch models dynamically from the UI.
- **Real-Time Observability**: Execution traces, memory usage, and token consumption metrics updated via WebSockets (`Socket.IO`).
- **Containerized Architecture**: Everything is bundled via Docker-Compose, making scaling and local deployment trivial.

---

## 🏗 System Architecture

The project consists of several independent modules orchestrated by Docker:

- **`core/`**: Contains the FastAPI Orchestrator (`main.py`) which manages the SQLite database, queue system, global locking, and serves the REST/WebSocket API.
- **`web-cli/`**: The Frontend UI (HTML/CSS/JS) served via Nginx. Connects to the Orchestrator via API proxy.
- **`prompts/`**: JSON files storing system instructions and persona traits for each agent role (`teamlead.json`, `frontend.json`, vb.).
- **`agent/`**: Python backend script templates for the isolated execution workers (`agent.py`).
- **`docker/`**: Dockerfiles to build the Orchestrator, Agent Workers, and Web CLI containers.

---

## 📦 Installation & Setup

### Prerequisites
- [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/)
- Modern Web Browser
- (Optional) NVIDIA GPU hardware for fast Ollama inference (if not available, change `runtime: nvidia` in `docker-compose.yml`).

### Quick Start

1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd has-ai-team
   ```

2. **Start the environment using Docker Compose:**
   ```bash
   docker-compose up -d --build
   ```
   *This command will spin up the Nginx Web-CLI, FastAPI Orchestrator, Ollama Server, and the Agent Worker containers.*

3. **Open the Web CLI:**
   Navigate to `http://localhost:4000` (or the configured `WEB_CLI` port) in your web browser.

---

## ⚙️ Configuration

You can configure the behavior of the orchestrator through the UI or `data/config.json`.
In the **Settings** tab of the Web CLI, you can setup:
- **LLM Provider**: Switch between Local `Ollama` or Remote `OpenAI Compatible` endpoints.
- **Ollama Server URL**: Keep default (`http://has-ai-ollama:11434`) for internal Docker communication.
- **Primary Agent Model**: Select an active LLM Model from a dynamically populated dropdown fetched from Ollama.
- **Pull New Model**: Easily download new models (e.g., `phi3`, `qwen`) straight from the UI. *Note: Timeout limits are extended up to 20 mins to allow pulling large variants.*

---

## 🛡 How A Project (Sprint) Works

1. **Planning**: Through the `Dashboard` input, describe your project idea to the **TeamLead**. The TeamLead draft an architectural proposal and tasks (Preview Mode).
2. **Approval**: Review the TeamLead's JSON plan. Click "Build Plan & Execute".
3. **Execution Pipeline**: The Orchestrator automatically splits tasks based on the defined Plan and queues them up.
4. **Agent Action**: `Frontend` and `Backend` agents lock their tasks from the queue and write code to the `apps/<project_name>` folder.
5. **Quality Assurance**: Once implementation is complete, `Tester` and `Security` agents kick in to run audits and unit tests automatically.

---

## 🛠 Tech Stack

- **Backend / Orchestrator:** Python, FastAPI, SQLAlchemy, Socket.IO
- **Frontend / Control Center:** HTML5, CSS3, Vanilla JS, Nginx
- **LLM Engine:** Ollama (Local AI)
- **Containerization:** Docker & Docker Compose

---

## 📄 License
This system is developed for the **HAS AI STUDIO**. All rights reserved or licensed accordingly depending on usage.

---
**Developed by** [@fathasss](https://github.com/fathasss)
