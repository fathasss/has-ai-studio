import os
import re
import json
import subprocess
import shutil
from typing import List, Tuple, Optional
from .config import logger


# ═══════════════════════════════════════════════════════════════════
# DÜZELTME 1: DEPENDENCY_REGISTRY kullanıldığı fonksiyondan ÖNCE
# tanımlandı. "type": "pip" alanı da eklendi (önceden eksikti,
# install_dependencies içindeki pip sanal ortam mantığı hiç
# çalışmıyordu).
# ═══════════════════════════════════════════════════════════════════
DEPENDENCY_REGISTRY = [
    {"trigger": "package.json",     "command": "npm install",                        "mode": "exact"},
    {"trigger": "requirements.txt", "command": None,                                  "mode": "exact",  "type": "pip"},
    {"trigger": ".csproj",          "command": "dotnet restore",                      "mode": "suffix"},
    {"trigger": ".sln",             "command": "dotnet restore",                      "mode": "suffix"},
    {"trigger": "go.mod",           "command": "go mod download",                     "mode": "exact"},
    {"trigger": "build.gradle",     "command": "chmod +x ./gradlew && ./gradlew build", "mode": "exact"},
    {"trigger": "pom.xml",          "command": "mvn install",                         "mode": "exact"},
    {"trigger": "Cargo.toml",       "command": "cargo build",                         "mode": "exact"},
]


def map_role(role: str) -> str:
    if not role or not role.strip():
        logger.warning("map_role called with empty role, defaulting to 'Backend'")
        return "Backend"

    r = role.lower().strip()

    EXACT_MAP = {
        "devops":    "DevOps",
        "backend":   "Backend",
        "frontend":  "Frontend",
        "tester":    "Tester",
        "security":  "Security",
        "teamlead":  "TeamLead",
        "team lead": "TeamLead",
        "qa":        "Tester",
    }
    if r in EXACT_MAP:
        return EXACT_MAP[r]

    def has_word(text: str, *words: str) -> bool:
        return any(re.search(rf'\b{re.escape(w)}\b', text) for w in words)

    if has_word(r, "devops", "infrastructure", "pipeline", "ci", "cd", "deploy"):
        return "DevOps"
    if has_word(r, "tester", "qa", "test", "bug", "quality"):
        return "Tester"
    if has_word(r, "security", "audit", "pentest", "vulnerability"):
        return "Security"
    if has_word(r, "auth", "authentication", "authorization"):
        if has_word(r, "api", "server", "service", "backend"):
            return "Backend"
        return "Security"
    if has_word(r, "frontend", "ui", "ux", "css", "html", "react", "vue", "angular"):
        return "Frontend"
    if has_word(r, "backend", "api", "server", "database", "db", "microservice"):
        return "Backend"
    if has_word(r, "devops", "setup", "provision", "infra"):
        return "DevOps"
    if has_word(r, "init", "initialize", "bootstrap"):
        if has_word(r, "database", "db", "migration", "schema"):
            return "Backend"
        return "DevOps"
    if has_word(r, "lead", "manager", "architect", "coordinator"):
        return "TeamLead"

    logger.warning(f"map_role: unrecognized role '{role}', defaulting to 'Backend'")
    return "Backend"


def safe_json_loads(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()

    def clean_json_str(s: str) -> str:
        if not s:
            return ""
        s = re.sub(r"^```[a-zA-Z0-9]*\s*\n", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\n```$", "", s)

        cleaned = ""
        in_string = False
        i = 0

        while i < len(s):
            char = s[i]
            if in_string:
                if char == '\\':
                    if i + 1 < len(s):
                        next_char = s[i + 1]
                        if next_char in '"\/bfnrt':
                            cleaned += char + next_char
                            i += 2
                            continue
                        elif next_char == 'u' and i + 5 < len(s):
                            hex_seq = s[i+2:i+6]
                            if re.match(r'^[0-9a-fA-F]{4}$', hex_seq):
                                cleaned += s[i:i+6]
                                i += 6
                                continue
                        cleaned += '\\\\'
                        i += 1
                        continue
                    else:
                        cleaned += '\\\\'
                        i += 1
                        continue
                elif char == '"':
                    in_string = False
                    cleaned += char
                else:
                    code = ord(char)
                    if code < 32:
                        if char == '\n':   cleaned += '\\n'
                        elif char == '\r': cleaned += '\\r'
                        elif char == '\t': cleaned += '\\t'
                        else:              cleaned += f'\\u{code:04x}'
                    else:
                        cleaned += char
            else:
                if char == '"':
                    in_string = True
                cleaned += char
            i += 1

        cleaned = re.sub(r',\s*\}', '}', cleaned)
        cleaned = re.sub(r',\s*\]', ']', cleaned)
        return cleaned.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    json_blocks = re.findall(r"```[a-zA-Z0-9]*\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    candidates = []
    for block in json_blocks:
        try:
            parsed = json.loads(clean_json_str(block.strip()))
            candidates.append(parsed)
        except Exception:
            pass

    if candidates:
        for c in candidates:
            if isinstance(c, dict) and "tasks" in c:
                return c
        return candidates[0]

    # Parantez sayacı ile doğru JSON bloğunu bul
    best_candidate = None
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            in_str = False
            j = i
            while j < len(text):
                c = text[j]
                if c == '"' and (j == 0 or text[j-1] != '\\'):
                    in_str = not in_str
                if not in_str:
                    if c == '{':
                        depth += 1
                    elif c == '}':
                        depth -= 1
                        if depth == 0:
                            candidate_str = text[i:j+1]
                            try:
                                parsed = json.loads(clean_json_str(candidate_str))
                                if isinstance(parsed, dict) and "tasks" in parsed:
                                    return parsed
                                if best_candidate is None or len(candidate_str) > len(str(best_candidate)):
                                    best_candidate = parsed
                            except Exception:
                                pass
                            break
                j += 1
        i += 1

    if best_candidate is not None:
        return best_candidate

    pmatch = re.search(r'"project_name"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
    if pmatch:
        return {"project_name": pmatch.group(1)}

    return None


def extract_setup_commands(text: str, project_dir: str) -> List[str]:
    project_basename = os.path.basename(project_dir).lower()

    pattern = r"### SETUP:\s*(.*?)(?=\n### FILE:|\n\[TARGET FILE\]:|$)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if not match:
        return []

    raw_commands = match.group(1).strip().splitlines()
    commands = []

    for cmd in raw_commands:
        cmd = cmd.strip()
        if not cmd or cmd.startswith("#"):
            continue

        prefix_pat = (
            rf"(?:apps/|workspace/|\./|{re.escape(project_basename)}/"
            rf"|sprint-[a-zA-Z0-9_-]+/)+"
        )
        parts_raw = cmd.split(" ")
        cleaned_parts = [
            re.sub(rf"^{prefix_pat}", "", token, flags=re.IGNORECASE)
            for token in parts_raw
        ]
        cmd = " ".join(cleaned_parts).strip()

        parts = cmd.split()
        if not parts:
            continue

        is_init = any(x in cmd.lower() for x in ["create-", "init", "startproject"])
        if is_init and len(parts) > 1:
            TOOL_KEYWORDS = {"npx", "python", "python3", "poetry", "uv", "pip", "node", "yarn", "pnpm"}
            new_parts = list(parts)
            replaced = False

            for i, p in enumerate(new_parts):
                if p.lower() == project_basename and not replaced:
                    new_parts[i] = "."
                    replaced = True
                    break

            if not replaced and ("create-" in parts[0].lower() or (len(parts) > 1 and "create-" in parts[1].lower())):
                for i in range(1, len(new_parts)):
                    if not new_parts[i].startswith("-") and new_parts[i].lower() not in TOOL_KEYWORDS:
                        new_parts[i] = "."
                        replaced = True
                        break

            if replaced:
                cmd = " ".join(new_parts)
            parts = cmd.split()

        if re.match(
            rf"^(mkdir|cd)\s+(-p\s+)?{re.escape(project_basename)}$",
            cmd.strip(),
            re.IGNORECASE,
        ):
            continue

        FILE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".html", ".env", ".json"}
        if parts[0].lower() == "mkdir":
            suspicious_targets = [
                p for p in parts[1:]
                if not p.startswith("-") and any(p.endswith(ext) for ext in FILE_EXTENSIONS)
            ]
            if suspicious_targets:
                logger.warning(f"Blocking suspicious mkdir for potential file(s): {suspicious_targets} in cmd: {cmd}")
                continue

        commands.append(cmd)

    return commands


def validate_content(filename: str, content: str) -> Tuple[bool, str]:
    ext = os.path.splitext(filename)[1].lower()

    MARKDOWN_LEAKAGE_MARKERS = ["```", "### FILE:", "[TARGET FILE]:"]
    for marker in MARKDOWN_LEAKAGE_MARKERS:
        if marker in content:
            return False, f"Content appears to contain raw LLM markdown: '{marker}' found"

    first_line = content.lstrip().splitlines()[0] if content.strip() else ""
    if first_line.startswith("Note:") or first_line.startswith("NOTE:"):
        return False, "Content appears to be a note/explanation, not code"

    if ext == '.py':
        try:
            compile(content, filename, 'exec')
            return True, ""
        except SyntaxError as e:
            return False, f"Python Syntax Error: {e.msg} at line {e.lineno}"

    if ext == '.json':
        try:
            json.loads(content)
            return True, ""
        except json.JSONDecodeError as e:
            return False, f"JSON Error: {e.msg} at line {e.lineno}"

    if ext in ['.js', '.jsx', '.ts', '.tsx']:
        stripped = re.sub(r'"(?:\\.|[^"\\])*"', '""', content)
        stripped = re.sub(r"'(?:\\.|[^'\\])*'", "''", stripped)
        stripped = re.sub(r"`(?:\\.|[^`\\])*`", "``", stripped)
        open_count  = stripped.count('{')
        close_count = stripped.count('}')
        if open_count != close_count:
            return False, (
                f"Probable syntax error: unbalanced braces "
                f"(open={open_count}, close={close_count})"
            )

    return True, ""


def extract_files(text: str, project_dir: str, sprint_id: str = None, agent_name: str = None):
    from .models import ProjectException
    from .database import SessionLocal

    if agent_name == "TeamLead":
        # DÜZELTME: Sadece 'saf' plan ise atla. Eğer içerisinde dosya marker'ı varsa çıkart.
        is_plan = '"tasks":' in text and '"role":' in text
        has_files = "### FILE:" in text.upper() or "[TARGET FILE]:" in text.upper()
        if is_plan and not has_files:
            logger.info(f"Skipping file extraction for TeamLead JSON plan (Sprint: {sprint_id})")
            return 0

    os.makedirs(project_dir, exist_ok=True)
    files_created = []

    setup_commands = extract_setup_commands(text, project_dir)
    if setup_commands:
        logger.info(f"Agent-defined setup detected for {sprint_id or 'workspace'}. Commands: {setup_commands}")
        execute_setup_commands(setup_commands, project_dir, sprint_id)

    file_markers = list(re.finditer(
        r"(?m)^\s*(?:### FILE:|\[TARGET FILE\]:)\s*([^ \n\r\*`\\:\[\]]+)",
        text, re.IGNORECASE
    ))

    for i, marker in enumerate(file_markers):
        raw_path = marker.group(1).strip()

        start_pos = marker.end()
        end_pos = file_markers[i+1].start() if i + 1 < len(file_markers) else len(text)
        search_area = text[start_pos:end_pos]

        code_block_match = re.search(r"```(?:\w+)?\n(.*?)\n```", search_area, re.DOTALL)
        if code_block_match:
            content = code_block_match.group(1).strip()
        else:
            content = search_area.strip()

        content = re.sub(r"^```(?:\w+)?\n", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
        content = content.lstrip("`").rstrip("`").strip()

        rel_path = raw_path.replace("\\", "/").lstrip("/")
        project_basename = os.path.basename(project_dir)

        path_parts = rel_path.split("/")
        while path_parts:
            first = path_parts[0].lower()
            if first in ["apps", project_basename.lower(), "workspace", ".", ""]:
                path_parts.pop(0)
            elif first.startswith("sprint-"):
                path_parts.pop(0)
            elif len(path_parts) > 1 and first == path_parts[1].lower():
                path_parts.pop(0)
            else:
                break

        rel_path = "/".join(path_parts).rstrip("/")

        if ".." in rel_path or not rel_path:
            continue

        full_path = os.path.join(project_dir, rel_path)

        if not os.path.abspath(full_path).startswith(os.path.abspath(project_dir)):
            logger.warning(f"Malicious path detected and blocked: {rel_path}")
            continue

        is_valid, err_msg = validate_content(rel_path, content)
        if not is_valid:
            logger.warning(f"Validation failed for {rel_path}: {err_msg}")
            if sprint_id:
                log_project_exception(sprint_id, "extract_files", f"VALIDATE {rel_path}", err_msg)
            # DÜZELTME 5: Geçersiz içerik yazılmaya devam ediyor — bu bilinçli karar
            # ama en azından flag ile işaretleniyor ki caller ayırt edebilsin.
            # Tamamen engellemek istiyorsanız burada `continue` ekleyin.

        try:
            if os.path.exists(full_path) and os.path.isdir(full_path):
                logger.warning(f"Conflict: Directory exists where file should be: {full_path}. Removing...")
                shutil.rmtree(full_path)

            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            files_created.append(rel_path)
            logger.info(f"Extracted: {full_path}")
        except Exception as e:
            logger.error(f"Extract failed {raw_path}: {e}")
            if sprint_id:
                log_project_exception(sprint_id, "extract_files", f"WRITE {rel_path}", str(e))

    if files_created:
        install_dependencies(project_dir, sprint_id)

    return len(files_created)


def install_dependencies(project_dir: str, sprint_id: str = None):
    executed_commands: set = set()

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [
            d for d in dirs
            if not d.startswith('.')
            and d not in {'node_modules', 'venv', '.venv', '__pycache__', 'dist', 'build', 'bin', 'obj'}
        ]

        for rule in DEPENDENCY_REGISTRY:
            trigger = rule["trigger"]
            mode    = rule["mode"]
            command = rule.get("command")
            kind    = rule.get("type")

            match_found = (
                (mode == "exact"  and trigger in files) or
                (mode == "suffix" and any(f.endswith(trigger) for f in files))
            )
            if not match_found:
                continue

            # DÜZELTME 1 (devam): "type": "pip" artık DEPENDENCY_REGISTRY'de mevcut,
            # bu yüzden kind == "pip" koşulu artık gerçekten tetikleniyor.
            if kind == "pip":
                venv_pip = None
                for venv_name in ("venv", ".venv"):
                    candidate = os.path.join(root, venv_name, "bin", "pip")
                    if os.path.isfile(candidate):
                        venv_pip = candidate
                        break
                command = (
                    f"{venv_pip} install -r requirements.txt"
                    if venv_pip
                    else "pip3 install --user -r requirements.txt"
                )

            registry_key = f"{root}:{command}"
            if registry_key in executed_commands:
                logger.info(f"Skipping already-executed command in {root}: {command}")
                continue

            logger.info(f"Trigger '{trigger}' found in {root}. Executing: {command}")
            execute_setup_commands([command], root, sprint_id)
            executed_commands.add(registry_key)


def execute_setup_commands(commands: List[str], project_dir: str, sprint_id: str = None):
    os.makedirs(project_dir, exist_ok=True)
    custom_env = os.environ.copy()
    base_sdk_dir = "/opt/sdks"
    paths_to_add = ["/usr/local/go/bin", base_sdk_dir]

    if os.path.exists(base_sdk_dir):
        for item in os.listdir(base_sdk_dir):
            full_path = os.path.join(base_sdk_dir, item)
            if os.path.isdir(full_path):
                paths_to_add.append(full_path)
                bin_path = os.path.join(full_path, "bin")
                if os.path.exists(bin_path):
                    paths_to_add.append(bin_path)

    current_path = custom_env.get("PATH", "")
    added_count = 0
    for p in paths_to_add:
        if os.path.exists(p) and p not in current_path:
            current_path = f"{p}:{current_path}"
            added_count += 1

    if added_count > 0:
        custom_env["PATH"] = current_path
        logger.info(f"Dynamically added {added_count} SDK paths.")

    for cmd in commands:
        if not cmd.strip():
            continue
        try:
            logger.info(f"Executing: {cmd} in {project_dir}")
            process = subprocess.run(
                cmd, shell=True, cwd=project_dir,
                capture_output=True, text=True,
                timeout=1200, env=custom_env
            )
            if process.returncode != 0:
                err_msg = process.stderr or process.stdout
                logger.warning(f"Command failed: {cmd}. Error: {err_msg}")
                if sprint_id:
                    # DÜZELTME 2: Mevcut log_project_exception helper'ı kullanılıyor.
                    # Önceden burada inline DB session açılıyordu ve finally yoktu
                    # → connection leak riski. Helper zaten try/finally kullanıyor.
                    log_project_exception(sprint_id, "execute_setup_commands", cmd, err_msg)
            else:
                logger.info(f"Command success: {cmd}")
        except Exception as e:
            logger.error(f"Command execution error: {cmd}. Error: {e}")
            if sprint_id:
                log_project_exception(sprint_id, "execute_setup_commands", cmd, str(e))


def get_latest_reports(sprint_id: str) -> str:
    workspace_root = os.path.join("workspace", sprint_id)
    if not os.path.exists(workspace_root):
        return ""

    reports_content = []
    agent_dirs = sorted(os.listdir(workspace_root))

    for agent_dir in agent_dirs:
        agent_path = os.path.join(workspace_root, agent_dir)
        if not os.path.isdir(agent_path):
            continue

        files = [f for f in os.listdir(agent_path) if f.startswith("report_") and f.endswith(".md")]
        if not files:
            continue

        # DÜZELTME 4: Alfabetik sort sayısal sıralamayı bozar (report_9 > report_10).
        # Dosya adındaki sayıyı çıkararak sayısal sırala.
        def report_sort_key(fname: str) -> int:
            m = re.search(r'(\d+)', fname)
            return int(m.group(1)) if m else 0

        latest_report = sorted(files, key=report_sort_key)[-1]

        try:
            with open(os.path.join(agent_path, latest_report), "r", encoding="utf-8") as f:
                content = f.read().strip()

            handover_match = re.search(
                r"## Technical Handover Notes\n(.*?)(?=\n## Results Summary|\n---|$)",
                content, re.DOTALL
            )
            handover = handover_match.group(1).strip() if handover_match else ""

            if handover and "*No detailed handover notes*" not in handover:
                reports_content.append(f"### [MANDATORY] {agent_dir} Technical Handover:\n{handover}")
            else:
                summary_match = re.search(
                    r"## Results Summary\n(.*?)(?=\n###|\n---|$)",
                    content, re.DOTALL
                )
                summary = summary_match.group(1).strip() if summary_match else "Task completed."
                reports_content.append(f"### {agent_dir} Work Summary:\n{summary}")
        except Exception as e:
            logger.error(f"Error reading report {latest_report}: {e}")

    return "\n\n".join(reports_content)


def get_project_context(project_dir: str, sprint_id: str = None) -> str:
    context = []

    if sprint_id:
        reports = get_latest_reports(sprint_id)
        if reports:
            context.append("# CRITICAL: WORK COMPLETED BY OTHER AGENTS (MUST READ)\n" + reports)

    context.append("# CURRENT PROJECT STRUCTURE")
    tree = []
    if os.path.exists(project_dir):
        for root, dirs, files in os.walk(project_dir):
            dirs[:] = [
                d for d in dirs
                if not d.startswith('.')
                and d not in ['node_modules', 'venv', '__pycache__', 'dist', 'build', 'bin', 'obj']
            ]
            level = root.replace(project_dir, '').count(os.sep)
            indent = '  ' * level
            tree.append(f"{indent}{os.path.basename(root)}/")
            for f in files:
                tree.append(f"{indent}  {f}")

    context.append("\n".join(tree) if tree else "[Project directory is currently empty]")

    readme_path = os.path.join(project_dir, "README.md")
    if os.path.exists(readme_path):
        # DÜZELTME 3: Bare except kaldırıldı, hata loglanıyor.
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                context.append("\n# PROJECT OVERVIEW (README)\n" + f.read().strip())
        except Exception as e:
            logger.warning(f"Could not read README.md: {e}")

    return "\n\n".join(context)


def log_project_exception(sprint_id: str, source: str, command: str, error_message: str):
    from .models import ProjectException
    from .database import SessionLocal
    db = SessionLocal()
    try:
        exc = ProjectException(
            sprint_id=sprint_id,
            source=source,
            command=command,
            error_message=error_message
        )
        db.add(exc)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log project exception: {e}")
    finally:
        db.close()


def task_to_prompt(t: dict) -> str:
    """
    Converts a task dict to an agent prompt string.
    Supports both old schema (task string) and new schema (structured fields).
    """
    # Geriye dönük uyumluluk: eski schema
    if "task" in t and isinstance(t["task"], str):
        return t["task"]

    parts = []

    target = t.get("target_file", "")
    if target:
        parts.append(f"[TARGET FILE]: {target}")

    file_action = t.get("file_action", "CREATE")
    parts.append(f"[ACTION]: {file_action}")

    description = t.get("description", "")
    if description:
        parts.append(f"[LOGIC]: {description}")

    deps = t.get("dependencies", [])
    if deps:
        dep_str = ", ".join(deps) if isinstance(deps, list) else str(deps)
        parts.append(f"[DEPENDENCIES]: {dep_str}")

    criteria = t.get("acceptance_criteria", [])
    if criteria:
        criteria_lines = "\n".join(f"  - {c}" for c in criteria)
        parts.append(f"[ACCEPTANCE CRITERIA]:\n{criteria_lines}")

    return "\n".join(parts)