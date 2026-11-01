import os
import re
from datetime import datetime
from typing import Dict, Any, List, Optional
from .. import config

class MemoryService:
    @staticmethod
    def get_memory_dir(target_dir: str, sprint_id: str) -> str:
        """Returns the primary memory directory for the project."""
        mem_dir = os.path.join(target_dir, "memory") if target_dir else os.path.join("workspace", sprint_id, "memory")
        os.makedirs(mem_dir, exist_ok=True)
        return mem_dir

    @staticmethod
    def init_project_memory(sprint_id: str, plan: Dict[str, Any], target_dir: str):
        """
        Initializes the shared project memory and individual agent memory files.
        """
        mem_dir = MemoryService.get_memory_dir(target_dir, sprint_id)
        ws_mem_dir = os.path.join("workspace", sprint_id, "memory")
        os.makedirs(ws_mem_dir, exist_ok=True)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        project_name = plan.get("project_name") or sprint_id
        arch_summary = plan.get("architecture") or plan.get("architecture_summary") or plan.get("summary_tr") or "Multi-Agent System Architecture"

        shared_memory_template = f"""# 🧠 {project_name.upper()} — ORTAK PROJE TEKNİK HAFIZASI
*Oluşturulma Tarihi: {now_str}*
*Bu hafıza projedeki tüm ajanlar (DevOps, Database, Backend, Frontend, Security, Tester, Documenter) tarafından ortaklaşa okunur ve her görevde güncellenir.*

---

## 1. 🏗️ Mimari Kararlar & Teknoloji Yığını
- **Proje Adı**: `{project_name}`
- **Mimari Özet**: {arch_summary}
- **Temel Standartlar**:
  - Kodlama Dili & Framework: Belirlenen plana ve `.env` şablonuna sadık kalınacaktır.
  - Kod Organizasyonu: Modüler, SOLID uyumlu, açık uç bırakmayan üretim kalitesinde implementasyon.

---

## 2. 🗄️ Veri Tabanı Modelleri & Şema Sözleşmeleri
*(Database ajanı tarafından güncellenir)*
- *Henüz kaydedilmiş model bulunmuyor. İlk veritabanı göreviyle şemalar buraya işlenecektir.*

---

## 3. ⚙️ REST API Endpoint'leri & İstek/Cevap Sözleşmeleri
*(Backend ajanı tarafından güncellenir - Frontend bu sözleşmelere göre kodlar)*
- *Henüz kaydedilmiş endpoint bulunmuyor.*

---

## 4. 🎨 Frontend Sayfa Rotaları, Bileşenleri & UI Durumu
*(Frontend ajanı tarafından güncellenir)*
- *Henüz kaydedilmiş rota bulunmuyor.*

---

## 5. 🛡️ Güvenlik, Kimlik Doğrulama & Yetkilendirme Kuralları
*(Security ajanı tarafından denetlenir ve güncellenir)*
- Kimlik Doğrulama: JWT / Token tabanlı güvenli oturum.
- Parola Hashleme: bcrypt veya argon2.
- CORS: Güvenli origin politikası.

---

## 6. 🧪 Test Doğrulama & Çözülen Hatalar Günlüğü
*(Tester ve Security ajanları tarafından güncellenir)*
- *Test raporları ve loopback düzeltmeleri buraya işlenecektir.*

---
*HAS AI Software Studio — Project Memory Engine v2.0*
"""
        for mdir in [mem_dir, ws_mem_dir]:
            shared_path = os.path.join(mdir, "PROJECT_MEMORY.md")
            with open(shared_path, "w", encoding="utf-8") as f:
                f.write(shared_memory_template)

            # Agent individual memory files
            agents = ["DevOps", "Database", "Backend", "Frontend", "Security", "Tester", "Documenter", "TeamLead"]
            for a in agents:
                a_file = os.path.join(mdir, f"{a}_memory.md")
                if not os.path.exists(a_file):
                    with open(a_file, "w", encoding="utf-8") as f:
                        f.write(f"# 👤 @{a} — Bireysel Proje Hafızası\n- **Proje**: `{project_name}`\n- **Rol**: `{a}`\n\n## İcra Edilen Görevler & Teknik Çıktılar:\n")

        config.logger.info(f"Initialized project memory in {mem_dir}")

    @staticmethod
    def get_project_memory_prompt(sprint_id: str, agent: str, target_dir: str) -> str:
        """
        Reads PROJECT_MEMORY.md and {agent}_memory.md and formats them as a prompt injection block.
        """
        mem_dir = MemoryService.get_memory_dir(target_dir, sprint_id)
        shared_path = os.path.join(mem_dir, "PROJECT_MEMORY.md")
        agent_path = os.path.join(mem_dir, f"{agent}_memory.md")

        parts = []

        if os.path.exists(shared_path):
            try:
                with open(shared_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    parts.append(
                        "# 🧠 ACCUMULATED PROJECT MEMORY & TECHNICAL CONTRACTS (MUST RESPECT)\n"
                        "The team has established the following technical decisions, schema models, and API contracts.\n"
                        "You MUST align your implementation strictly with this memory (use exact table names, API paths, and types):\n\n"
                        + content
                    )
            except Exception as e:
                config.logger.warning(f"Could not read shared project memory: {e}")

        if os.path.exists(agent_path):
            try:
                with open(agent_path, "r", encoding="utf-8") as f:
                    a_content = f.read().strip()
                if a_content and len(a_content) > 100:
                    parts.append(
                        f"\n## 👤 YOUR PRIOR MEMORY FOR THIS PROJECT (@{agent}):\n"
                        + a_content[-1500:] # Last 1500 chars of agent memory
                    )
            except Exception as e:
                config.logger.warning(f"Could not read agent memory: {e}")

        return "\n\n".join(parts) if parts else ""

    @staticmethod
    def update_agent_memory(sprint_id: str, agent: str, target_dir: str, prompt: str, resp_text: str, extracted_files: List[str]):
        """
        Extracts new endpoints, models, and technical notes from agent response
        and updates PROJECT_MEMORY.md and {agent}_memory.md.
        """
        mem_dir = MemoryService.get_memory_dir(target_dir, sprint_id)
        shared_path = os.path.join(mem_dir, "PROJECT_MEMORY.md")
        agent_path = os.path.join(mem_dir, f"{agent}_memory.md")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Extract handover
        handover_match = re.search(
            r"### TECHNICAL_HANDOVER:\s*(.*?)(?=\n### FILE:|\n\[TARGET FILE\]:|\n### RESULT:|\n### STATUS:|$)",
            resp_text, re.DOTALL | re.IGNORECASE
        )
        handover = handover_match.group(1).strip() if handover_match else ""

        # Extract endpoints: e.g. @app.get("/..."), router.post("/..."), def get_users()
        endpoints = re.findall(r"@(?:app|router|api)\.(get|post|put|delete|patch)\([\"']([^\"']+)[\"']", resp_text, re.IGNORECASE)

        # Extract models: e.g. class User(Base):, interface User {
        models = re.findall(r"class\s+([A-Za-z0-9_]+)\s*\((?:Base|Model|Schema|pydantic|declarative_base)[^\)]*\):", resp_text)

        # 1. Update individual agent memory
        if os.path.exists(agent_path):
            try:
                with open(agent_path, "a", encoding="utf-8") as f:
                    f.write(f"\n### 📌 [{now_str}] Görev Çıktısı\n")
                    if extracted_files:
                        f.write(f"- **Oluşturulan Dosyalar**: {', '.join(f'`{f}`' for f in extracted_files)}\n")
                    if endpoints:
                        f.write(f"- **Tanımlanan API Endpoint'leri**: {', '.join(f'`{m.upper()} {p}`' for m, p in endpoints)}\n")
                    if models:
                        f.write(f"- **Oluşturulan Modeller**: {', '.join(f'`{m}`' for m in models)}\n")
                    if handover:
                        f.write(f"- **Teknik Not**: {handover[:300]}\n")
            except Exception as e:
                config.logger.warning(f"Could not update {agent_path}: {e}")

        # 2. Update shared project memory
        if os.path.exists(shared_path):
            try:
                with open(shared_path, "r", encoding="utf-8") as f:
                    content = f.read()

                updated = False

                # If Database agent and found models, append under section 2
                if agent == "Database" and models:
                    section_target = "## 2. 🗄️ Veri Tabanı Modelleri & Şema Sözleşmeleri"
                    if section_target in content:
                        add_str = f"\n- **[{now_str}] @Database**: Eklenen Modeller: {', '.join(f'`{m}`' for m in models)} (Dosyalar: {', '.join(extracted_files)})\n"
                        content = content.replace(section_target, section_target + add_str, 1)
                        updated = True

                # If Backend agent and found endpoints, append under section 3
                if agent == "Backend" and endpoints:
                    section_target = "## 3. ⚙️ REST API Endpoint'leri & İstek/Cevap Sözleşmeleri"
                    if section_target in content:
                        ep_str = ", ".join(f"`{m.upper()} {p}`" for m, p in endpoints)
                        add_str = f"\n- **[{now_str}] @Backend**: Aktif Endpoint'ler: {ep_str}\n"
                        content = content.replace(section_target, section_target + add_str, 1)
                        updated = True

                # If Frontend agent, append under section 4
                if agent == "Frontend" and extracted_files:
                    section_target = "## 4. 🎨 Frontend Sayfa Rotaları, Bileşenleri & UI Durumu"
                    if section_target in content:
                        add_str = f"\n- **[{now_str}] @Frontend**: Geliştirilen UI Bileşenleri / Dosyalar: {', '.join(f'`{f}`' for f in extracted_files)}\n"
                        content = content.replace(section_target, section_target + add_str, 1)
                        updated = True

                # If Security agent, append under section 5
                if agent == "Security" and handover:
                    section_target = "## 5. 🛡️ Güvenlik, Kimlik Doğrulama & Yetkilendirme Kuralları"
                    if section_target in content:
                        add_str = f"\n- **[{now_str}] @Security Denetim Özeti**: {handover[:250]}\n"
                        content = content.replace(section_target, section_target + add_str, 1)
                        updated = True

                # If Tester agent, append under section 6
                if agent == "Tester" and handover:
                    section_target = "## 6. 🧪 Test Doğrulama & Çözülen Hatalar Günlüğü"
                    if section_target in content:
                        add_str = f"\n- **[{now_str}] @Tester Kalite Notu**: {handover[:250]}\n"
                        content = content.replace(section_target, section_target + add_str, 1)
                        updated = True

                if updated:
                    with open(shared_path, "w", encoding="utf-8") as f:
                        f.write(content)
            except Exception as e:
                config.logger.warning(f"Could not update {shared_path}: {e}")

    @staticmethod
    def get_all_memory(sprint_id: str, target_dir: str) -> Dict[str, Any]:
        """Reads shared memory and all agent memory files for API/UI."""
        mem_dir = MemoryService.get_memory_dir(target_dir, sprint_id)
        shared_path = os.path.join(mem_dir, "PROJECT_MEMORY.md")
        
        shared_text = ""
        if os.path.exists(shared_path):
            with open(shared_path, "r", encoding="utf-8") as f:
                shared_text = f.read()

        agent_memories = {}
        agents = ["DevOps", "Database", "Backend", "Frontend", "Security", "Tester", "Documenter", "TeamLead"]
        for a in agents:
            a_path = os.path.join(mem_dir, f"{a}_memory.md")
            if os.path.exists(a_path):
                with open(a_path, "r", encoding="utf-8") as f:
                    agent_memories[a] = f.read()

        return {
            "sprint_id": sprint_id,
            "shared_memory": shared_text,
            "agent_memories": agent_memories
        }

