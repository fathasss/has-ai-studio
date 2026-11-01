import os
import re
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from ..utils import map_role, safe_json_loads
from .. import config

def _slugify(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "_", text).strip("_")

class PhaseService:
    @staticmethod
    def get_phase_dir(target_dir: str, sprint_id: str) -> str:
        """Returns the primary phases directory for the given project."""
        p_dir = os.path.join(target_dir, "phases") if target_dir else os.path.join("workspace", sprint_id, "phases")
        os.makedirs(p_dir, exist_ok=True)
        return p_dir

    @staticmethod
    def generate_project_phases(sprint_id: str, plan: Dict[str, Any], target_dir: str) -> List[Dict[str, Any]]:
        """
        Creates project-driven dynamic phases based on project requirements and tasks.
        Saves them as structured Markdown (.md) files in the project's phases/ directory.
        """
        phase_dir = PhaseService.get_phase_dir(target_dir, sprint_id)
        # Also ensure workspace/sprint_id/phases exists for backup
        ws_phase_dir = os.path.join("workspace", sprint_id, "phases")
        os.makedirs(ws_phase_dir, exist_ok=True)

        project_name = plan.get("project_name") or sprint_id
        tasks = plan.get("tasks", [])

        # 1. Determine Dynamic Phases
        # If the plan already specified dynamic phases, use them:
        raw_phases = plan.get("phases", [])
        structured_phases: List[Dict[str, Any]] = []

        if raw_phases and isinstance(raw_phases, list):
            for idx, p in enumerate(raw_phases, 1):
                p_id = p.get("phase_id", idx)
                p_name = p.get("name") or f"Faz {p_id}"
                p_goal = p.get("goal") or p.get("description") or "Faz geliştirme hedefleri"
                p_agents = p.get("participating_agents") or p.get("agents") or []
                
                # Link tasks
                p_task_ids = p.get("task_ids") or p.get("tasks") or []
                assigned_tasks = []
                for t in tasks:
                    tid = t.get("task_id", "")
                    if tid in p_task_ids or t.get("phase_id") == p_id or str(t.get("phase", "")).lower() == p_name.lower():
                        assigned_tasks.append(t)
                        role = map_role(t.get("role", ""))
                        if role and role not in p_agents:
                            p_agents.append(role)

                structured_phases.append({
                    "phase_id": p_id,
                    "name": p_name,
                    "goal": p_goal,
                    "participating_agents": p_agents,
                    "status": "PENDING",
                    "tasks": assigned_tasks,
                    "deliverables": [t.get("target_file") for t in assigned_tasks if t.get("target_file")],
                })
        else:
            # Dynamically group tasks into project-driven milestone phases:
            # Analyze all tasks in the project to create balanced, logical milestone phases
            phase_groups: Dict[str, List[Dict[str, Any]]] = {}
            for t in tasks:
                raw_phase = t.get("phase") or "Core Implementation"
                phase_groups.setdefault(raw_phase, []).append(t)

            if len(phase_groups) >= 2:
                for idx, (p_name, p_tasks) in enumerate(phase_groups.items(), 1):
                    p_agents = list(set(map_role(t.get("role", "")) for t in p_tasks if t.get("role")))
                    structured_phases.append({
                        "phase_id": idx,
                        "name": p_name,
                        "goal": f"{p_name} kapsamındaki mimari ve kodlama görevlerinin icrası",
                        "participating_agents": p_agents,
                        "status": "PENDING",
                        "tasks": p_tasks,
                        "deliverables": [t.get("target_file") for t in p_tasks if t.get("target_file")],
                    })
            else:
                # Default 3 to 4 sequential project milestones incorporating multiple agents
                # Phase 1: MVP Setup & Architecture Skeleton (DevOps + Database + Base Backend)
                p1_tasks = [t for t in tasks if map_role(t.get("role", "")) in ["DevOps", "Database"]]
                p1_agents = list(set(map_role(t.get("role", "")) for t in p1_tasks)) or ["DevOps", "Database"]
                
                # Phase 2: Core Domain Logic & User Interface (Backend + Frontend)
                p2_tasks = [t for t in tasks if map_role(t.get("role", "")) in ["Backend", "Frontend"]]
                p2_agents = list(set(map_role(t.get("role", "")) for t in p2_tasks)) or ["Backend", "Frontend"]

                # Phase 3: Security Hardening, Synthetic Testing & Delivery (Security + Tester + Documenter + TeamLead)
                p3_tasks = [t for t in tasks if map_role(t.get("role", "")) in ["Security", "Tester", "Documenter", "TeamLead"]]
                p3_agents = list(set(map_role(t.get("role", "")) for t in p3_tasks)) or ["Security", "Tester", "Documenter"]

                # Any remaining
                used_tasks = set(id(t) for t in (p1_tasks + p2_tasks + p3_tasks))
                unassigned = [t for t in tasks if id(t) not in used_tasks]
                if unassigned:
                    p2_tasks.extend(unassigned)

                structured_phases = [
                    {
                        "phase_id": 1,
                        "name": "Çekirdek Altyapı, Veritabanı & MVP İskeleti",
                        "goal": "Container çalışma ortamı, paket bağımlılıkları ve temel veritabanı şema modelleri",
                        "participating_agents": p1_agents,
                        "status": "IN_PROGRESS",
                        "tasks": p1_tasks,
                        "deliverables": [t.get("target_file") for t in p1_tasks if t.get("target_file")],
                    },
                    {
                        "phase_id": 2,
                        "name": "İş Mantığı Servisleri, REST API & Kullanıcı Arayüzü",
                        "goal": "Core API endpointleri, iş kuralları, veri erişim katmanı ve responsive kullanıcı arayüzü",
                        "participating_agents": p2_agents,
                        "status": "PENDING",
                        "tasks": p2_tasks,
                        "deliverables": [t.get("target_file") for t in p2_tasks if t.get("target_file")],
                    },
                    {
                        "phase_id": 3,
                        "name": "Güvenlik Denetimi, Sentetik Kullanıcı Testleri & Canlı Teslimat",
                        "goal": "OWASP açık taraması, unit ve entegrasyon testleri, API dokümantasyonu ve teslim raporu",
                        "participating_agents": p3_agents,
                        "status": "PENDING",
                        "tasks": p3_tasks,
                        "deliverables": [t.get("target_file") for t in p3_tasks if t.get("target_file")],
                    }
                ]

        # 2. Write Markdown Files
        PhaseService._write_phase_markdown_files(phase_dir, project_name, structured_phases)
        PhaseService._write_phase_markdown_files(ws_phase_dir, project_name, structured_phases)

        config.logger.info(f"Generated {len(structured_phases)} project-driven phase markdown files in {phase_dir}")
        return structured_phases

    @staticmethod
    def _write_phase_markdown_files(phase_dir: str, project_name: str, phases: List[Dict[str, Any]]):
        """Writes ROADMAP.md and individual PHASE_X.md files."""
        os.makedirs(phase_dir, exist_ok=True)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. ROADMAP.md
        roadmap_lines = [
            f"# 🗺️ {project_name.upper()} — PROJE GELİŞTİRME FAZLARI YOL HARİTASI",
            f"*Oluşturulma Tarihi: {now_str}*",
            "",
            "Bu proje, yazılımın ihtiyaçlarına göre gruplandırılmış aşamalar (Phases) halinde geliştirilmektedir.",
            "Her fazda birden fazla ajan işbirliği içinde çalışabilir.",
            "",
            "## 📌 Faz Özeti",
            "",
            "| Faz | Başlık | Hedef | Sorumlu Ajanlar | Görev Sayısı | Durum |",
            "|---|---|---|---|---|---|",
        ]

        for p in phases:
            agents_str = ", ".join(f"`@{a}`" for a in p["participating_agents"])
            status_badge = "⚡ ÇALIŞIYOR" if p["status"] == "IN_PROGRESS" else ("✅ TAMAMLANDI" if p["status"] == "COMPLETED" else "⏳ BEKLİYOR")
            roadmap_lines.append(
                f"| Faz {p['phase_id']} | **{p['name']}** | {p['goal'][:50]}... | {agents_str} | {len(p['tasks'])} | {status_badge} |"
            )

        roadmap_lines.extend([
            "",
            "---",
            "### 📁 Ayrıntılı Faz Dosyaları:",
        ])
        for p in phases:
            slug = _slugify(p["name"])
            filename = f"PHASE_{p['phase_id']}_{slug}.md"
            roadmap_lines.append(f"- [{p['name']}](./{filename}) — `@{', @'.join(p['participating_agents'])}`")

        roadmap_path = os.path.join(phase_dir, "ROADMAP.md")
        with open(roadmap_path, "w", encoding="utf-8") as f:
            f.write("\n".join(roadmap_lines))

        # 2. Individual PHASE_X.md files
        for p in phases:
            slug = _slugify(p["name"])
            p_file = os.path.join(phase_dir, f"PHASE_{p['phase_id']}_{slug}.md")
            
            p_lines = [
                f"# 🚀 Faz {p['phase_id']}: {p['name']}",
                f"- **Proje**: `{project_name}`",
                f"- **Durum**: `{p['status']}`",
                f"- **Son Güncelleme**: `{now_str}`",
                f"- **Görevli Ajanlar**: {', '.join(f'`@{a}`' for a in p['participating_agents'])}",
                "",
                "## 🎯 Faz Amacı & Kapsamı",
                f"> {p['goal']}",
                "",
                "## 📦 Hedef Çıktılar & Dosyalar",
            ]
            if p["deliverables"]:
                for d in p["deliverables"]:
                    p_lines.append(f"- 📄 `{d}`")
            else:
                p_lines.append("- *Hedef dosyalar dinamik belirlenmektedir.*")

            p_lines.extend([
                "",
                "## 📋 Faz Görev Listesi",
                "",
                "| ID | Ajan | Eylem | Hedef Dosya | Açıklama | Kabul Kriteri | Durum |",
                "|---|---|---|---|---|---|---|",
            ])

            for t in p["tasks"]:
                tid = t.get("task_id", "GÖREV")
                role = map_role(t.get("role", "Developer"))
                action = t.get("file_action", "CREATE")
                tfile = t.get("target_file", "-")
                desc = (t.get("description") or t.get("task") or "").replace("\n", " ")[:60]
                crit = "; ".join(t.get("acceptance_criteria", []))[:40] or "-"
                p_lines.append(f"| {tid} | `@{role}` | {action} | `{tfile}` | {desc}... | {crit} | `BEKLİYOR` |")

            p_lines.extend([
                "",
                "## 📝 Ajan Çıktı Günlüğü & Teknik Notlar",
                "*Ajanlar görevleri icra ettikçe teknik handover notları buraya otomatik işlenecektir.*",
                "",
            ])

            with open(p_file, "w", encoding="utf-8") as f:
                f.write("\n".join(p_lines))

    @staticmethod
    def record_agent_task_execution(sprint_id: str, agent: str, target_dir: str, prompt: str, resp_text: str, extracted_files: List[str]):
        """
        Updates the active phase markdown file when an agent completes a task.
        """
        phase_dir = PhaseService.get_phase_dir(target_dir, sprint_id)
        if not os.path.exists(phase_dir):
            return

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Find matching phase files
        files = [f for f in os.listdir(phase_dir) if f.startswith("PHASE_") and f.endswith(".md")]
        files.sort()

        # Extract handover snippet
        handover_match = re.search(
            r"### TECHNICAL_HANDOVER:\s*(.*?)(?=\n### FILE:|\n\[TARGET FILE\]:|\n### RESULT:|\n### STATUS:|$)",
            resp_text, re.DOTALL | re.IGNORECASE
        )
        handover_notes = handover_match.group(1).strip() if handover_match else "Görev başarıyla icra edildi."

        target_file_match = re.search(r"\[TARGET FILE\]:\s*([^\n]+)", prompt)
        target_file = target_file_match.group(1).strip() if target_file_match else ""

        entry = f"""
### ⚡ [{now_str}] @{agent} Görev Çıktısı
- **İcra Edilen Görev / Hedef**: `{target_file or 'Genel Görev'}`
- **Oluşturulan / Değiştirilen Dosyalar**: {', '.join(f'`{f}`' for f in extracted_files) if extracted_files else '*Belirtilmedi*'}
- **Teknik Notlar & Handover**:
  > {handover_notes[:400]}...

---
"""
        # Append to relevant phase file
        for fname in files:
            fpath = os.path.join(phase_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()

                # Check if this phase includes this agent or file
                if f"@{agent}`" in content or (target_file and target_file in content):
                    # Mark task as completed in table
                    if target_file and f"`{target_file}`" in content:
                        content = re.sub(
                            rf"(\|[^|]+\|[^|]+\|[^|]+\|\s*`{re.escape(target_file)}`\s*\|[^|]+\|[^|]+\|\s*)`BEKLİYOR`",
                            r"\1`TAMAMLANDI`",
                            content
                        )
                    content += entry
                    with open(fpath, "w", encoding="utf-8") as f:
                        f.write(content)
                    break
            except Exception as e:
                config.logger.warning(f"Failed to append to phase file {fname}: {e}")

    @staticmethod
    def get_phase_status_summary(sprint_id: str, target_dir: str, db=None) -> Optional[Dict[str, Any]]:
        """Reads phase markdown files or computes dynamic status."""
        phase_dir = PhaseService.get_phase_dir(target_dir, sprint_id)
        if not os.path.exists(phase_dir):
            return None

        roadmap_path = os.path.join(phase_dir, "ROADMAP.md")
        if not os.path.exists(roadmap_path):
            return None

        phases = []
        files = [f for f in os.listdir(phase_dir) if f.startswith("PHASE_") and f.endswith(".md")]
        files.sort()

        for idx, fname in enumerate(files, 1):
            fpath = os.path.join(phase_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    text = f.read()

                title_match = re.search(r"#\s*🚀\s*Faz\s*(\d+):\s*([^\n]+)", text)
                phase_id = int(title_match.group(1)) if title_match else idx
                phase_name = title_match.group(2).strip() if title_match else fname.replace(".md", "")

                goal_match = re.search(r"##\s*🎯\s*Faz Amacı & Kapsamı\s*\n>\s*([^\n]+)", text)
                goal = goal_match.group(1).strip() if goal_match else ""

                agents_match = re.search(r"- \*\*Görevli Ajanlar\*\*:\s*([^\n]+)", text)
                agents_str = agents_match.group(1) if agents_match else ""
                agents = [a.strip("`@ ") for a in re.findall(r"`@?([A-Za-z0-9_-]+)`", agents_str)]

                # Check tasks
                tasks_in_file = len(re.findall(r"\|\s*T\d+\s*\|", text))
                completed_tasks = len(re.findall(r"`TAMAMLANDI`", text))

                status = "PENDING"
                if completed_tasks > 0 and completed_tasks >= tasks_in_file:
                    status = "COMPLETED"
                elif completed_tasks > 0:
                    status = "IN_PROGRESS"

                deliverables = re.findall(r"- 📄 `([^`]+)`", text)

                phases.append({
                    "phase_id": phase_id,
                    "name": phase_name,
                    "goal": goal,
                    "participating_agents": agents,
                    "role": agents[0] if agents else "TeamLead",
                    "status": status,
                    "tasks_count": tasks_in_file,
                    "completed_tasks": completed_tasks,
                    "deliverables": deliverables,
                    "file_path": fpath
                })
            except Exception as e:
                config.logger.warning(f"Error parsing {fname}: {e}")

        if not phases:
            return None

        # Determine current phase
        current_phase = 1
        completed_count = sum(1 for p in phases if p["status"] == "COMPLETED")
        for p in phases:
            if p["status"] != "COMPLETED":
                current_phase = p["phase_id"]
                if p["status"] == "PENDING" and p["phase_id"] == completed_count + 1 and completed_count > 0:
                    p["status"] = "IN_PROGRESS"
                break

        overall_progress = int((completed_count / max(len(phases), 1)) * 100)
        return {
            "phases": phases,
            "current_phase": current_phase,
            "total_phases": len(phases),
            "completed_phases": completed_count,
            "overall_progress": overall_progress
        }

