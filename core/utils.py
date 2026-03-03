import os
import re
import json
import subprocess
import shutil
from typing import List, Tuple
from .config import logger

def map_role(role: str) -> str:
    r = role.lower()
    if "frontend" in r: return "Frontend"
    if "backend" in r: return "Backend"
    if "tester" in r or "qa" in r or "test" in r: return "Tester"
    if "security" in r or "auth" in r: return "Security"
    if "devops" in r or "setup" in r or "infrastructure" in r: return "DevOps"
    return "TeamLead"

def safe_json_loads(text: str):
    if not text:
        return None
    text = text.strip()
    
    def clean_json_str(s):
        if not s: return ""
        # Remove markdown fences if present within the block
        s = re.sub(r"^```[a-zA-Z0-9]*\s*\n", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\n```$", "", s)
        
        cleaned = ""
        in_string = False
        escaped = False
        
        i = 0
        while i < len(s):
            char = s[i]
            if in_string:
                if escaped:
                    cleaned += char
                    escaped = False
                elif char == '\\':
                    # Peek ahead
                    if i + 1 < len(s) and s[i+1] in '"\\/bfnrtu':
                        cleaned += char
                        escaped = True
                    else:
                        # Unescaped backslash
                        cleaned += '\\\\'
                elif char == '"':
                    in_string = False
                    cleaned += char
                else:
                    # Check for illegal control characters (0-31)
                    code = ord(char)
                    if code < 32:
                        if char == '\n': cleaned += '\\n'
                        elif char == '\r': cleaned += '\\r'
                        elif char == '\t': cleaned += '\\t'
                        else: cleaned += f'\\u{code:04x}'
                    else:
                        cleaned += char
            else:
                if char == '"':
                    in_string = True
                cleaned += char
            i += 1

        # Remove trailing commas in objects and arrays
        cleaned = re.sub(r',\s*\}', '}', cleaned)
        cleaned = re.sub(r',\s*\]', ']', cleaned)
        return cleaned.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except:
        pass
        
    # Extract from markdown blocks, allowing any language tag
    json_blocks = re.findall(r"```[a-zA-Z0-9]*\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    candidates = []
    for block in json_blocks:
        try:
            cleaned = clean_json_str(block.strip())
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "tasks" in parsed:
                return parsed
            candidates.append(parsed)
        except:
            pass
            
    if candidates:
        return candidates[0]

    # Try extracting the largest {} block
    start_idx = text.find('{')
    end_idx = text.rfind('}')
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate_str = text[start_idx:end_idx+1]
        try:
            return json.loads(clean_json_str(candidate_str.strip()))
        except:
            pass
            
    # Fallback to field extraction if all else fails
    fallback = {}
    pmatch = re.search(r'"project_name"\s*:\s*"([^"]+)"', text, re.IGNORECASE)
    if pmatch:
        fallback["project_name"] = pmatch.group(1)
    
    return fallback if fallback else None

def extract_setup_commands(text: str) -> List[str]:
    """Parses LLM output for the ### SETUP: block and returns a list of commands."""
    import re
    pattern = r"### SETUP:\s*(.*?)(?=\n### FILE:|\n\[TARGET FILE\]:|$)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        raw_commands = match.group(1).strip().splitlines()
        # Clean up whitespace and empty lines
        return [cmd.strip() for cmd in raw_commands if cmd.strip()]
    return []

def validate_content(filename: str, content: str) -> Tuple[bool, str]:
    """Basic syntax validation based on file extension."""
    ext = os.path.splitext(filename)[1].lower()
    
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
        # Basic check for balanced braces/parens if node is not available
        # In a real environment, we'd use 'node --check' or 'tsc'
        # For now, we'll just check if it's not obviously truncated/markdown
        if "```" in content or "Note:" in content[:50] or content.count('{') != content.count('}'):
             if content.count('{') != content.count('}') and abs(content.count('{') - content.count('}')) > 5:
                 return False, "Probable syntax error: unbalanced braces"
    
    return True, ""

def extract_files(text: str, project_dir: str, sprint_id: str = None):
    """Parses LLM output for file content and writes to disk with multiple fallback patterns."""
    from .models import ProjectException
    from .database import SessionLocal
    
    os.makedirs(project_dir, exist_ok=True)
    files_created = []
    
    # Process Agent-Defined Setup Commands
    setup_commands = extract_setup_commands(text)
    if setup_commands:
        logger.info(f"Agent-defined setup detected for {sprint_id or 'workspace'}. Commands: {setup_commands}")
        execute_setup_commands(setup_commands, project_dir, sprint_id)

    # Improved Pattern: Find FILE marker, then find THE NEXT markdown code block
    # This avoids "markdown leakage" by isolating only the code block.
    file_markers = list(re.finditer(r"(?:### FILE:|\[TARGET FILE\]:)\s*([^ \n\r\*`]+)", text, re.IGNORECASE))
    
    for i, marker in enumerate(file_markers):
        raw_path = marker.group(1).strip()
        
        # Define the range to search for the code block: from current marker to next marker (or end of text)
        start_pos = marker.end()
        end_pos = file_markers[i+1].start() if i + 1 < len(file_markers) else len(text)
        search_area = text[start_pos:end_pos]
        
        # Find the first markdown block in this search area
        code_block_match = re.search(r"```(?:\w+)?\n(.*?)\n```", search_area, re.DOTALL)
        if code_block_match:
            content = code_block_match.group(1).strip()
        else:
            # Fallback for markers without blocks (sometimes they just put the code after the marker)
            content = search_area.strip()
            # Clean up accidental trailing fences if they exists
            content = re.sub(r"```$", "", content).strip()

        # Sanitize path
        rel_path = raw_path.replace("\\", "/").lstrip("/")
        project_basename = os.path.basename(project_dir)
        path_parts = rel_path.split("/")
        
        if path_parts[0] == "apps":
            path_parts.pop(0)
            if path_parts and path_parts[0] == project_basename:
                path_parts.pop(0)
        elif path_parts[0] == project_basename:
            path_parts.pop(0)
            
        rel_path = "/".join(path_parts)
        
        if ".." in rel_path or not rel_path:
            continue
            
        # Validation Pass
        is_valid, err_msg = validate_content(rel_path, content)
        if not is_valid:
            logger.warning(f"Validation failed for {rel_path}: {err_msg}")
            if sprint_id:
                log_project_exception(sprint_id, "extract_files", f"VALIDATE {rel_path}", err_msg)
            # We still write it so the user/tester can see it, but we've logged the error
            
        full_path = os.path.join(project_dir, rel_path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            if not os.path.abspath(full_path).startswith(os.path.abspath(project_dir)):
                logger.warning(f"Malicious path detected and blocked: {rel_path}")
                continue

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            files_created.append(rel_path)
            logger.info(f"Extracted: {full_path}")
        except Exception as e:
            logger.error(f"Extract failed {raw_path}: {e}")
            if sprint_id:
                log_project_exception(sprint_id, "extract_files", f"WRITE {rel_path}", str(e))
    
    # Auto-install dependencies
    if files_created:
        install_dependencies(project_dir, sprint_id)
        
    return len(files_created)


# Dependency Installation Registry
# Maps trigger files to their respective installation commands.
DEPENDENCY_REGISTRY = [
    {"trigger": "package.json", "command": "npm install", "mode": "exact"},
    {"trigger": "requirements.txt", "command": "pip install -r requirements.txt", "mode": "exact"},
    {"trigger": ".csproj", "command": "dotnet restore", "mode": "suffix"},
    {"trigger": ".sln", "command": "dotnet restore", "mode": "suffix"},
    {"trigger": "go.mod", "command": "go mod download", "mode": "exact"},
    {"trigger": "build.gradle", "command": "./gradlew build", "mode": "exact"},
    {"trigger": "pom.xml", "command": "mvn install", "mode": "exact"},
    {"trigger": "Cargo.toml", "command": "cargo build", "mode": "exact"},
]

def install_dependencies(project_dir: str, sprint_id: str = None):
    """Recursively finds manifest files and installs dependencies using the Registry."""
    import os
    from .database import SessionLocal
    
    processed_dirs = set()

    for root, dirs, files in os.walk(project_dir):
        # Skip heavy or hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'venv', '__pycache__', 'dist', 'build', 'bin', 'obj']]
        
        for rule in DEPENDENCY_REGISTRY:
            trigger = rule["trigger"]
            mode = rule["mode"]
            command = rule["command"]
            
            match_found = False
            if mode == "exact" and trigger in files:
                match_found = True
            elif mode == "suffix" and any(f.endswith(trigger) for f in files):
                match_found = True
            
            registry_key = f"{root}:{command}"
            if match_found and registry_key not in processed_dirs:
                logger.info(f"Trigger {trigger} found in {root}. Executing: {command}...")
                execute_setup_commands([command], root, sprint_id)
                processed_dirs.add(registry_key)

def execute_setup_commands(commands: List[str], project_dir: str, sprint_id: str = None):
    from .models import ProjectException
    from .database import SessionLocal
    import os

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
        if not cmd.strip(): continue
        try:
            logger.info(f"Executing: {cmd} in {project_dir}")
            process = subprocess.run(
                cmd,
                shell=True,
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=1200,
                env=custom_env
            )
            if process.returncode != 0:
                err_msg = process.stderr or process.stdout
                logger.warning(f"Command failed: {cmd}. Error: {err_msg}")
                if sprint_id:
                    db = SessionLocal()
                    exc = ProjectException(sprint_id=sprint_id, source="execute_setup_commands", command=cmd, error_message=err_msg)
                    db.add(exc)
                    db.commit()
                    db.close()
            else:
                logger.info(f"Command success: {cmd}")
        except Exception as e:
            logger.error(f"Command execution error: {cmd}. Error: {e}")
            if sprint_id:
                db = SessionLocal()
                exc = ProjectException(sprint_id=sprint_id, source="execute_setup_commands", command=cmd, error_message=str(e))
                db.add(exc)
                db.commit()
                db.close()

def get_latest_reports(sprint_id: str) -> str:
    """Reads the most recent report from each agent in the workspace."""
    workspace_root = os.path.join("workspace", sprint_id)
    if not os.path.exists(workspace_root):
        return ""
    
    reports_content = []
    for agent_dir in os.listdir(workspace_root):
        agent_path = os.path.join(workspace_root, agent_dir)
        if os.path.isdir(agent_path):
            files = [f for f in os.listdir(agent_path) if f.startswith("report_") and f.endswith(".md")]
            if files:
                latest_report = sorted(files)[-1]
                try:
                    with open(os.path.join(agent_path, latest_report), "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        # Extract just the relevant parts to keep prompt size manageable
                        summary_match = re.search(r"## Results Summary\n(.*?)(?=\n###|\n---|$)", content, re.DOTALL)
                        summary = summary_match.group(1).strip() if summary_match else "N/A"
                        reports_content.append(f"### {agent_dir} Progress:\n{summary}")
                except Exception as e:
                    logger.error(f"Error reading report {latest_report}: {e}")
    
    return "\n\n".join(reports_content)

def get_project_context(project_dir: str, sprint_id: str = None) -> str:
    """Aggregates file tree, README, and agent reports into a single context string."""
    context = []
    
    # 1. Project File Tree
    context.append("# CURRENT PROJECT STRUCTURE")
    tree = []
    for root, dirs, files in os.walk(project_dir):
        # Filter unimportant dirs
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['node_modules', 'venv', '__pycache__', 'dist', 'build', 'bin', 'obj']]
        level = root.replace(project_dir, '').count(os.sep)
        indent = '  ' * level
        tree.append(f"{indent}{os.path.basename(root)}/")
        for f in files:
            tree.append(f"{indent}  {f}")
    
    context.append("\n".join(tree))
    
    # 2. README if available
    readme_path = os.path.join(project_dir, "README.md")
    if os.path.exists(readme_path):
        try:
            with open(readme_path, "r", encoding="utf-8") as f:
                context.append("\n# PROJECT OVERVIEW (README)\n" + f.read().strip())
        except: pass

    # 3. Agent Reports
    if sprint_id:
        reports = get_latest_reports(sprint_id)
        if reports:
            context.append("\n# RECENT AGENT ACTIVITY\n" + reports)
            
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
