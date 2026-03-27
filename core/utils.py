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


# ═══════════════════════════════════════════════════════════════════
# Cross-language detection: dosya uzantısına uymayan kod pattern'leri.
# Bir .py dosyasında Go kodu veya bir .go dosyasında Python kodu
# tespit edilirse validate_content başarısız döner.
# ═══════════════════════════════════════════════════════════════════
LANGUAGE_MISMATCH_RULES = {
    '.py': [
        (r'^\s*package\s+\w+', "Go 'package' declaration found in Python file"),
        (r'^\s*func\s+\w+\s*\(', "Go 'func' declaration found in Python file"),
        (r'^\s*import\s*\(\s*$', "Go multi-import block found in Python file"),
        (r'^\s*using\s+System', "C# 'using System' found in Python file"),
        (r'^\s*namespace\s+\w+', "C# 'namespace' found in Python file"),
        (r'^\s*public\s+class\s+', "Java/C# class found in Python file"),
    ],
    '.go': [
        (r'^\s*from\s+\w+\s+import\s+', "Python import found in Go file"),
        (r'^\s*def\s+\w+\s*\(', "Python function found in Go file"),
        (r'^\s*class\s+\w+', "Python class found in Go file"),
    ],
    '.cs': [
        (r'^\s*from\s+\w+\s+import\s+', "Python import found in C# file"),
        (r'^\s*def\s+\w+\s*\(', "Python function found in C# file"),
        (r'^\s*package\s+\w+', "Go package found in C# file"),
    ],
    '.java': [
        (r'^\s*from\s+\w+\s+import\s+', "Python import found in Java file"),
        (r'^\s*def\s+\w+\s*\(', "Python function found in Java file"),
    ],
    '.js': [
        (r'^\s*def\s+\w+\s*\(', "Python function found in JS file"),
    ],
    '.ts': [
        (r'^\s*def\s+\w+\s*\(', "Python function found in TS file"),
    ],
}

# ═══════════════════════════════════════════════════════════════════
# Framework conflict detection (Python): Aynı projede FastAPI ve Flask
# veya Django karıştırılmasını tespit eder.
# ═══════════════════════════════════════════════════════════════════
FRAMEWORK_SIGNATURES = {
    'fastapi': [r'from\s+fastapi\s+import', r'FastAPI\(\)'],
    'flask':   [r'from\s+flask\s+import',   r'Flask\(__name__\)', r'from\s+flask_login\s+import'],
    'django':  [r'from\s+django',           r'django\.'],
}


def detect_framework_in_content(content: str) -> Optional[str]:
    """Returns the dominant framework name found in content, or None."""
    for fw_name, patterns in FRAMEWORK_SIGNATURES.items():
        for pat in patterns:
            if re.search(pat, content, re.MULTILINE):
                return fw_name
    return None


def detect_project_framework(project_dir: str) -> Optional[str]:
    """Scans existing .py files in project_dir to find the dominant framework."""
    if not os.path.exists(project_dir):
        return None

    framework_counts: dict = {}
    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [
            d for d in dirs
            if not d.startswith('.') and d not in {
                'node_modules', 'venv', '.venv', '__pycache__',
                'dist', 'build', 'bin', 'obj', 'tests', 'test'
            }
        ]
        for fname in files:
            if not fname.endswith('.py'):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                    text = f.read()
                fw = detect_framework_in_content(text)
                if fw:
                    framework_counts[fw] = framework_counts.get(fw, 0) + 1
            except Exception:
                pass

    if not framework_counts:
        return None
    return max(framework_counts, key=framework_counts.get)


def get_project_language(project_dir: str) -> Optional[str]:
    """Reads the anchored project language from .project_meta if exists."""
    meta_path = os.path.join(project_dir, ".project_meta")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("language")
        except Exception:
            pass
    return None


def set_project_language(project_dir: str, lang: str):
    """Anchors the project to a specific language."""
    if not os.path.exists(project_dir):
        os.makedirs(project_dir, exist_ok=True)
    meta_path = os.path.join(project_dir, ".project_meta")
    try:
        data = {}
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        
        if "language" not in data:
            data["language"] = lang
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            logger.info(f"Project anchored to language: {lang}")
    except Exception as e:
        logger.error(f"Failed to set project language: {e}")


def repair_truncated_json(text: str) -> str:
    """Attempts to fix common LLM JSON truncation issues (missing closings)."""
    text = text.strip()
    if not text: return text
    
    # Sayaclar
    open_braces = text.count('{')
    close_braces = text.count('}')
    open_brackets = text.count('[')
    close_brackets = text.count(']')
    
    # Basit onarım: Eğer tırnaklar orantısızsa ve sonu tırnakla bitmiyorsa tırnak kapat
    if text.count('"') % 2 != 0:
        text += '"'
        
    # Brackets/Braces kapat
    while open_brackets > close_brackets:
        text += ']'
        close_brackets += 1
    while open_braces > close_braces:
        text += '}'
        close_braces += 1
        
    return text


# ═══════════════════════════════════════════════════════════════════
# Project-Aware Validation Helpers: Mantıksal ve altyapı tutarlılığı.
# ═══════════════════════════════════════════════════════════════════

def validate_python_local_imports(content: str, rel_path: str, project_dir: str, planned_files: List[str]) -> Tuple[bool, str]:
    """Ensures that local imports (starts with src. or current root modules) exist."""
    # Sadece 'src' ile başlayan veya projedeki klasör isimleriyle başlayanları yakala
    project_subdirs = {d for d in os.listdir(project_dir) if os.path.isdir(os.path.join(project_dir, d))}
    # Planned files'lardan da klasör isimlerini çıkar (belki henüz klasör yok diskte)
    for pf in planned_files:
        parts = pf.split('/')
        if len(parts) > 1: project_subdirs.add(parts[0])

    # from x.y import z
    # import x.y
    from_imports = re.findall(r'(?m)^\s*from\s+([a-zA-Z0-9_\.]+)\s+import', content)
    direct_imports = re.findall(r'(?m)^\s*import\s+([a-zA-Z0-9_\.]+)', content)
    
    all_imports = from_imports + direct_imports
    
    for imp in all_imports:
        parts = imp.split('.')
        root_mod = parts[0]
        
        # Eğer root module bir proje klasörü ise, bu bir local import kabul edilir
        if root_mod in project_subdirs or root_mod == 'src':
            # Dosya yolunu oluştur: src.db.database -> src/db/database.py
            target_rel_path = "/".join(parts) + ".py"
            target_rel_path_alt = "/".join(parts) + "/__init__.py"
            
            # 1. Diskte var mı?
            # 2. Şu anki extraction listesinde (planned_files) var mı?
            if target_rel_path not in planned_files and \
               target_rel_path_alt not in planned_files and \
               not os.path.exists(os.path.join(project_dir, target_rel_path)) and \
               not os.path.exists(os.path.join(project_dir, target_rel_path_alt)):
                return False, f"ModuleNotFoundError: Local module '{imp}' not found in project tree or planned files."
                
    return True, ""


def validate_docker_compose_consistency(content: str) -> Tuple[bool, str]:
    """Checks if database URLs in environment match services in the same file."""
    try:
        # Hallucination check: sqlite:latest image'ı uydurma bir pattern
        if re.search(r'image:\s*sqlite(?::latest)?', content, re.IGNORECASE):
            return False, "Docker-Compose error: 'sqlite:latest' is not a valid server image. SQLite is file-based."

        # DB URL'leri bul
        db_urls = re.findall(r'(postgresql|postgres|mysql|redis|mongodb)://', content, re.IGNORECASE)
        if not db_urls:
            return True, ""
            
        services = re.findall(r'(?m)^\s{2}([a-zA-Z0-9_-]+):', content)
        
        for db_type in db_urls:
            found_service = False
            db_type = db_type.lower()
            search_keywords = [db_type, 'db', 'database', 'sql']
            if any(kw in " ".join(services).lower() for kw in search_keywords):
                found_service = True
            
            # Hardening Phase 2: Artık uyarı değil, HATA.
            if not found_service:
                return False, f"Docker-Compose Error: Found '{db_type}' URL but no corresponding service (e.g., 'db' or '{db_type}') in services."
                
        return True, ""
    except Exception as e:
        return True, ""


def validate_dockerfile_paths(content: str, project_dir: str, planned_files: List[str]) -> Tuple[bool, str]:
    """Ensures that CMD/ENTRYPOINT refers to existing files."""
    # CMD ["uvicorn", "main:app", ...]
    # CMD ["python", "main.py"]
    # CMD python src/main.py
    
    cmd_match = re.search(r'(?m)^\s*(?:CMD|ENTRYPOINT)\s+(.*)', content)
    if not cmd_match:
        return True, ""
        
    cmd_val = cmd_match.group(1).strip()
    
    # Python + main.py senaryosu
    if "python" in cmd_val.lower() and (".py" in cmd_val.lower()):
        # main.py veya src/main.py gibi bir string ara
        file_matches = re.findall(r'([a-zA-Z0-9_\-\/]+\.py)', cmd_val)
        for f in file_matches:
            if f not in planned_files and not os.path.exists(os.path.join(project_dir, f)):
                return False, f"Dockerfile error: CMD targets '{f}' but file is missing or in a different directory."

    # Uvicorn: main:app
    if "uvicorn" in cmd_val.lower():
        # "main:app" veya "src.main:app"
        uv_match = re.search(r'["\']?([a-zA-Z0-9_\.]+):[a-zA-Z0-9_]+["\']?', cmd_val)
        if uv_match:
            mod_path = uv_match.group(1)
            target_rel = mod_path.replace('.', '/') + ".py"
            if target_rel not in planned_files and not os.path.exists(os.path.join(project_dir, target_rel)):
                return False, f"Dockerfile error: Uvicorn targets '{mod_path}' but '{target_rel}' not found. Check file location!"

    return True, ""


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
            cleaned = clean_json_str(block.strip())
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                # Truncated repair denemesi
                repaired = repair_truncated_json(cleaned)
                parsed = json.loads(repaired)
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


def validate_content(filename: str, content: str, project_framework: str = None, project_dir: str = None, planned_files: List[str] = None) -> Tuple[bool, str]:
    ext = os.path.splitext(filename)[1].lower()

    # Hardening Phase 2: Project Language Anchor Check
    if project_dir and ext in ['.py', '.go', '.cs', '.java', '.js', '.ts']:
        anchored_lang = get_project_language(project_dir)
        
        # Eğer henüz dil sabitlenmemişse, bu dosyanın dilini proje dili yapalım
        current_lang_map = {'.py': 'python', '.go': 'go', '.cs': 'csharp', '.java': 'java', '.js': 'javascript', '.ts': 'typescript'}
        current_lang = current_lang_map.get(ext)
        
        if not anchored_lang and current_lang:
            set_project_language(project_dir, current_lang)
            anchored_lang = current_lang
            
        if anchored_lang and current_lang and anchored_lang != current_lang:
            return False, f"Language Hybridization ERROR: Project is anchored to '{anchored_lang}' but file is '{current_lang}'. Mixing languages is forbidden."

    MARKDOWN_LEAKAGE_MARKERS = ["```", "### FILE:", "[TARGET FILE]:"]
    for marker in MARKDOWN_LEAKAGE_MARKERS:
        if marker in content:
            return False, f"Content appears to contain raw LLM markdown: '{marker}' found"

    first_line = content.lstrip().splitlines()[0] if content.strip() else ""
    if first_line.startswith("Note:") or first_line.startswith("NOTE:"):
        return False, "Content appears to be a note/explanation, not code"

    # Project-Aware Validations (Requires project_dir and planned_files)
    if project_dir and planned_files:
        if ext == '.py':
            is_ok, err = validate_python_local_imports(content, filename, project_dir, planned_files)
            if not is_ok: return False, err
            
        if filename.lower().endswith('dockerfile'):
            is_ok, err = validate_dockerfile_paths(content, project_dir, planned_files)
            if not is_ok: return False, err
            
        if filename.lower() == 'docker-compose.yml':
            is_ok, err = validate_docker_compose_consistency(content)
            if not is_ok: return False, err

    # RESULT signal leakage: Tester/Security agent'ın sonuç satırı dosya içeriği olmamalı
    stripped_content = content.strip()
    if re.match(r'^\s*\*{0,2}Result\s+Signal\*{0,2}\s*$', stripped_content, re.IGNORECASE):
        return False, "Content is a raw result signal, not code"
    if re.match(r'^\s*###\s*RESULT:\s*(PASSED|FAILED)\s*$', stripped_content, re.IGNORECASE):
        return False, "Content is a RESULT signal, not code"

    # Cross-language detection: dosya uzantısına uymayan kod pattern'leri
    if ext in LANGUAGE_MISMATCH_RULES:
        for pattern, msg in LANGUAGE_MISMATCH_RULES[ext]:
            if re.search(pattern, content, re.MULTILINE):
                return False, f"Language mismatch: {msg}"

    # Framework conflict detection (Python dosyaları için)
    if ext == '.py' and project_framework:
        content_fw = detect_framework_in_content(content)
        if content_fw and content_fw != project_framework:
            return False, (
                f"Framework conflict: file uses '{content_fw}' but project uses "
                f"'{project_framework}'. Mixing frameworks is not allowed."
            )

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

    # Proje içindeki mevcut dosyalardan dominant framework'ü tespit et.
    # Bu bilgi validate_content'e geçirilerek framework karışıklığı yakalanır.
    project_framework = detect_project_framework(project_dir)
    if project_framework:
        logger.info(f"Detected project framework: {project_framework}")

    setup_commands = extract_setup_commands(text, project_dir)
    if setup_commands:
        logger.info(f"Agent-defined setup detected for {sprint_id or 'workspace'}. Commands: {setup_commands}")
        execute_setup_commands(setup_commands, project_dir, sprint_id)

    file_markers = list(re.finditer(
        r"(?m)^\s*(?:### FILE:|\[TARGET FILE\]:)\s*([^ \n\r\*`\\:\[\]]+)",
        text, re.IGNORECASE
    ))

    # Pre-parse: Hangi dosyalar üretilecek? (Validation için gerekli)
    planned_files = []
    for m in file_markers:
        raw_p = m.group(1).strip().replace("\\", "/").lstrip("/")
        # Path temizleme mantığını burada da işlet ki tam liste olsun
        p_parts = raw_p.split("/")
        while p_parts:
            fst = p_parts[0].lower()
            if fst in ["apps", os.path.basename(project_dir).lower(), "workspace", ".", ""]: p_parts.pop(0)
            elif fst.startswith("sprint-"): p_parts.pop(0)
            else: break
        planned_files.append("/".join(p_parts).rstrip("/"))

    for i, marker in enumerate(file_markers):
        raw_path = marker.group(1).strip()
        rel_path = planned_files[i]

        if ".." in rel_path or not rel_path:
            continue

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

        full_path = os.path.join(project_dir, rel_path)

        if not os.path.abspath(full_path).startswith(os.path.abspath(project_dir)):
            logger.warning(f"Malicious path detected and blocked: {rel_path}")
            continue

        is_valid, err_msg = validate_content(rel_path, content, project_framework, project_dir, planned_files)
        if not is_valid:
            logger.warning(f"Validation BLOCKED for {rel_path}: {err_msg}")
            if sprint_id:
                log_project_exception(sprint_id, "extract_files", f"VALIDATE {rel_path}", err_msg)
            continue

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