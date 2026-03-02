import os
import re
import json
import subprocess
from typing import List
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

def extract_files(text: str, project_dir: str, sprint_id: str = None):
    """Parses LLM output for file content and writes to disk with multiple fallback patterns."""
    from .models import ProjectException
    from .database import SessionLocal
    
    os.makedirs(project_dir, exist_ok=True)
    files_created = []
    
    # Primary Pattern: ### FILE: or [TARGET FILE]: format
    pattern = r"(?:### FILE:|\[TARGET FILE\]:)\s*([^ \n\r\*`]+)(.*?)(?=(?:### FILE:|\[TARGET FILE\]:)|$)"
    matches = list(re.finditer(pattern, text, re.DOTALL | re.IGNORECASE))
    
    if not matches:
        # Fallback 1: checking for markdown blocks with // filename or # filename annotation
        pattern_md = r"```(?:\w+)?\s*(?://|#)\s*([\w\.\-/]+)\n(.*?)\n```"
        matches = list(re.finditer(pattern_md, text, re.DOTALL))

    for match in matches:
        raw_path = match.group(1).strip()
        content = match.group(2).strip()
        
        # If content still has markdown fences, strip them (common LLM error)
        # Using a more robust loop to strip nested fences if they exist
        while True:
            new_content = re.sub(r"^```(?:\w+)?\n", "", content)
            new_content = re.sub(r"\n```$", "", new_content)
            if new_content == content:
                break
            content = new_content.strip()
        
        # Sanitize path
        rel_path = raw_path.replace("\\", "/").lstrip("/")
        
        # Robust Path Sanitization: Avoid nesting like apps/ID/apps/ID
        # If the agent prefixed with 'apps/' or 'apps/ID/', strip it.
        project_basename = os.path.basename(project_dir)
        path_parts = rel_path.split("/")
        
        # Potential prefixes to strip
        if path_parts[0] == "apps":
            path_parts.pop(0)
            if path_parts and path_parts[0] == project_basename:
                path_parts.pop(0)
        elif path_parts[0] == project_basename:
            path_parts.pop(0)
            
        rel_path = "/".join(path_parts)
        
        if ".." in rel_path or not rel_path:
            continue
            
        full_path = os.path.join(project_dir, rel_path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            # Re-verify we don't accidentally write to root or outside project_dir
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
                db = SessionLocal()
                exc = ProjectException(sprint_id=sprint_id, source="extract_files", command=f"WRITE {rel_path}", error_message=str(e))
                db.add(exc)
                db.commit()
                db.close()
    
    # Auto-install dependencies if manifest files are created
    if files_created:
        install_dependencies(project_dir, sprint_id)
        
    return len(files_created)

def install_dependencies(project_dir: str, sprint_id: str = None):
    # This logic was mostly in main.py, I'm adapting it
    from .models import ProjectException
    from .database import SessionLocal
    
    # Generic logic: if package.json exists, npm install. If requirements.txt, pip install.
    if os.path.exists(os.path.join(project_dir, "package.json")):
        execute_setup_commands(["npm install"], project_dir, sprint_id)
    if os.path.exists(os.path.join(project_dir, "requirements.txt")):
        execute_setup_commands(["pip install -r requirements.txt"], project_dir, sprint_id)

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
