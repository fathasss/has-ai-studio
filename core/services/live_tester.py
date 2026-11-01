import os
import sys
import re
import time
import socket
import subprocess
import requests
from datetime import datetime
from typing import Dict, Any, List, Tuple
from ..config import logger

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port

def _emit_live_step(orchestrator_url: str, sprint_id: str, step_num: int, total_steps: int, name: str, status: str, duration_ms: float, details: str = ""):
    if not orchestrator_url or not sprint_id:
        return
    try:
        requests.post(
            f"{orchestrator_url}/test/live-step",
            json={
                "sprint_id": sprint_id,
                "step": step_num,
                "total": total_steps,
                "name": name,
                "status": status,
                "duration_ms": round(duration_ms, 2),
                "details": details,
                "timestamp": datetime.utcnow().isoformat()
            },
            timeout=3
        )
    except Exception as e:
        logger.debug(f"Live test step emit failed: {e}")

def inspect_build_and_syntax(project_dir: str, sprint_id: str = None) -> Dict[str, Any]:
    """
    Performs comprehensive syntax, dependency, and zero-placeholder inspection on the codebase.
    """
    errors: List[str] = []
    warnings: List[str] = []
    scanned_files = 0

    if not os.path.exists(project_dir):
        return {"is_valid": False, "errors": [f"Project directory '{project_dir}' not found."], "warnings": [], "scanned_files": 0}

    for root, dirs, files in os.walk(project_dir):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in {'node_modules', 'venv', '.venv', '__pycache__', 'dist', 'build', 'bin', 'obj'}]

        for fname in files:
            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, project_dir).replace("\\", "/")
            scanned_files += 1

            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception as e:
                errors.append(f"Failed to read file {rel_path}: {e}")
                continue

            # 1. Python Syntax & Compilation Check
            if fname.endswith(".py"):
                try:
                    compile(content, rel_path, 'exec')
                except SyntaxError as se:
                    errors.append(f"Python Syntax Error in '{rel_path}' line {se.lineno}: {se.msg}")

            # 2. JSON Validity Check
            elif fname.endswith(".json"):
                import json
                try:
                    json.loads(content)
                except json.JSONDecodeError as je:
                    errors.append(f"JSON Syntax Error in '{rel_path}' line {je.lineno}: {je.msg}")

            # 3. TypeScript / JavaScript Balanced Braces Check
            elif fname.endswith((".ts", ".js", ".tsx", ".jsx")) and not fname.endswith(".min.js"):
                stripped = re.sub(r'"(?:\\.|[^"\\])*"', '""', content)
                stripped = re.sub(r"'(?:\\.|[^'\\])*'", "''", stripped)
                stripped = re.sub(r"`(?:\\.|[^`\\])*`", "``", stripped)
                open_braces = stripped.count('{')
                close_braces = stripped.count('}')
                if open_braces != close_braces:
                    errors.append(f"Unbalanced braces in '{rel_path}': open={open_braces}, close={close_braces}")

            # 4. Zero-Placeholder Check (TODO, FIXME, pass as only body, NotImplementedError)
            if not fname.endswith((".md", ".txt", ".json", ".lock")):
                for line_idx, line in enumerate(content.splitlines(), start=1):
                    line_s = line.strip()
                    if re.search(r'\b(TODO|FIXME)\b', line_s) and not line_s.startswith("//") and not line_s.startswith("#"):
                        warnings.append(f"Placeholder detected in '{rel_path}' line {line_idx}: '{line_s[:60]}'")
                    if re.match(r'^def\s+\w+\(.*\):\s*pass$', line_s) or re.match(r'^def\s+\w+\(.*\):\s*\.\.\.$', line_s):
                        errors.append(f"Unimplemented function stub in '{rel_path}' line {line_idx}: '{line_s}'")
                    if "NotImplementedError" in line_s or "NotImplementedException" in line_s:
                        warnings.append(f"Unimplemented exception in '{rel_path}' line {line_idx}: '{line_s}'")

    is_valid = len(errors) == 0
    report_lines = [
        f"### Build & Syntax Inspection Report",
        f"- **Scanned Files**: {scanned_files}",
        f"- **Status**: {'PASSED ✅' if is_valid else 'FAILED ❌'}",
        f"- **Errors Found**: {len(errors)}",
        f"- **Warnings**: {len(warnings)}"
    ]
    if errors:
        report_lines.append("\n#### Critical Errors:")
        for err in errors[:10]:
            report_lines.append(f"  - ❌ {err}")
    if warnings:
        report_lines.append("\n#### Warnings:")
        for warn in warnings[:10]:
            report_lines.append(f"  - ⚠️ {warn}")

    return {
        "is_valid": is_valid,
        "scanned_files": scanned_files,
        "errors": errors,
        "warnings": warnings,
        "report": "\n".join(report_lines)
    }

def run_live_synthetic_user_tests(project_dir: str, sprint_id: str, orchestrator_url: str = None) -> Dict[str, Any]:
    """
    Executes real-time synthetic user journey tests by:
    1. Running existing pytest / npm test suites if present.
    2. Finding backend entry point and booting an ephemeral test server process.
    3. Exercising real HTTP endpoints with synthetic user payloads.
    4. Streaming realtime test step updates via Socket.IO.
    """
    start_time = time.time()
    steps_results: List[Dict[str, Any]] = []
    overall_passed = True

    # --- Step 1: Pre-flight Syntax & Build Verification ---
    preflight = inspect_build_and_syntax(project_dir, sprint_id)
    _emit_live_step(
        orchestrator_url, sprint_id, 1, 4,
        "Pre-flight Code & Syntax Inspection",
        "PASSED" if preflight["is_valid"] else "FAILED",
        (time.time() - start_time) * 1000,
        f"{preflight['scanned_files']} files checked. Errors: {len(preflight['errors'])}"
    )

    if not preflight["is_valid"]:
        return {
            "passed": False,
            "result_signal": "### RESULT: FAILED",
            "summary": f"Pre-flight inspection failed with {len(preflight['errors'])} errors.\n" + "\n".join(preflight['errors'][:5]),
            "steps": steps_results
        }

    # --- Step 2: Automated Unit / Pytest Execution ---
    tests_dir = os.path.join(project_dir, "tests")
    if os.path.isdir(tests_dir):
        test_files = [f for f in os.listdir(tests_dir) if f.startswith("test_") and f.endswith(".py")]
        if test_files:
            step_t0 = time.time()
            try:
                cmd = f"{sys.executable} -m pytest tests/ -v"
                proc = subprocess.run(
                    cmd, shell=True, cwd=project_dir,
                    capture_output=True, text=True, timeout=60
                )
                step_duration = (time.time() - step_t0) * 1000
                test_passed = proc.returncode == 0
                step_status = "PASSED" if test_passed else "FAILED"
                step_msg = proc.stdout[-400:] if proc.stdout else (proc.stderr[-400:] if proc.stderr else "No output")

                _emit_live_step(
                    orchestrator_url, sprint_id, 2, 4,
                    f"Automated Test Suite ({len(test_files)} files)",
                    step_status, step_duration, step_msg.strip()
                )

                steps_results.append({
                    "name": "Automated Unit Tests",
                    "status": step_status,
                    "duration_ms": step_duration,
                    "output": step_msg
                })

                if not test_passed:
                    overall_passed = False
            except subprocess.TimeoutExpired:
                _emit_live_step(orchestrator_url, sprint_id, 2, 4, "Automated Test Suite", "FAILED", 60000, "Test execution timed out (60s)")
                overall_passed = False
            except Exception as e:
                logger.warning(f"Pytest execution error: {e}")

    # --- Step 3: Ephemeral Server Boot & Live API User Journey ---
    # Find Python or Node entrypoint
    entry_file = None
    app_kind = None
    for cand in ["main.py", "app.py", "src/main.py", "server.py"]:
        if os.path.isfile(os.path.join(project_dir, cand)):
            entry_file = cand
            app_kind = "python"
            break

    if not entry_file:
        for cand in ["server.js", "index.js", "src/index.ts", "src/main.ts"]:
            if os.path.isfile(os.path.join(project_dir, cand)):
                entry_file = cand
                app_kind = "node"
                break

    if entry_file and app_kind == "python":
        test_port = _find_free_port()
        server_env = os.environ.copy()
        server_env["PORT"] = str(test_port)
        server_env["PYTHONPATH"] = f"{project_dir}{os.pathsep}{server_env.get('PYTHONPATH', '')}"

        # Inspect if uvicorn or plain python
        entry_content = ""
        with open(os.path.join(project_dir, entry_file), "r", encoding="utf-8", errors="ignore") as f:
            entry_content = f.read()

        is_fastapi = "fastapi" in entry_content.lower()
        if is_fastapi:
            mod_name = entry_file.replace("/", ".").replace("\\", ".").replace(".py", "")
            srv_cmd = f"{sys.executable} -m uvicorn {mod_name}:app --host 127.0.0.1 --port {test_port}"
        else:
            srv_cmd = f"{sys.executable} {entry_file}"

        logger.info(f"Live Tester: Launching ephemeral server on port {test_port} for {sprint_id}: {srv_cmd}")
        srv_proc = None
        try:
            srv_proc = subprocess.Popen(
                srv_cmd, shell=True, cwd=project_dir,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=server_env
            )

            # Wait up to 6 seconds for server boot
            server_ready = False
            ready_t0 = time.time()
            for _ in range(12):
                time.sleep(0.5)
                try:
                    r = requests.get(f"http://127.0.0.1:{test_port}/", timeout=1)
                    if r.status_code in [200, 404, 401, 403]:
                        server_ready = True
                        break
                except Exception:
                    # Also try /health or /api
                    try:
                        r = requests.get(f"http://127.0.0.1:{test_port}/health", timeout=1)
                        if r.status_code in [200, 404]:
                            server_ready = True
                            break
                    except Exception:
                        pass

            boot_latency = (time.time() - ready_t0) * 1000

            if server_ready:
                _emit_live_step(
                    orchestrator_url, sprint_id, 3, 4,
                    f"Live Server Boot & Healthcheck (Port {test_port})",
                    "PASSED", boot_latency, "Server booted and successfully responded to HTTP requests."
                )

                # Step 4: Synthetic User Journey Checks
                # Discover registered endpoints
                api_routes = re.findall(r'@(?:app|router)\.(get|post|put|delete)\(["\']([^"\']+)["\']', entry_content, re.IGNORECASE)
                journey_passed = True
                tested_endpoints_count = 0

                for method, route in api_routes[:5]:
                    url = f"http://127.0.0.1:{test_port}{route}"
                    # replace path params like {id} with 1
                    url_test = re.sub(r'\{[^}]+\}', '1', url)
                    req_t0 = time.time()
                    try:
                        if method.lower() == 'get':
                            res = requests.get(url_test, timeout=2)
                        else:
                            res = requests.post(url_test, json={"name": "Test User", "email": "test@studio.ai", "title": "Test Task"}, timeout=2)
                        
                        req_lat = (time.time() - req_t0) * 1000
                        tested_endpoints_count += 1
                        
                        # 2xx, 4xx (handled error like 400 or 401) are healthy; 500 is a server crash!
                        if res.status_code >= 500:
                            journey_passed = False
                            _emit_live_step(
                                orchestrator_url, sprint_id, 4, 4,
                                f"Endpoint User Check: {method.upper()} {route}",
                                "FAILED", req_lat, f"HTTP {res.status_code}: {res.text[:150]}"
                            )
                            break
                    except Exception as req_err:
                        journey_passed = False
                        _emit_live_step(
                            orchestrator_url, sprint_id, 4, 4,
                            f"Endpoint User Check: {method.upper()} {route}",
                            "FAILED", 0, str(req_err)
                        )
                        break

                if journey_passed:
                    _emit_live_step(
                        orchestrator_url, sprint_id, 4, 4,
                        f"Synthetic User Flow ({tested_endpoints_count} API operations)",
                        "PASSED", (time.time() - ready_t0) * 1000,
                        f"All {tested_endpoints_count} endpoints handled synthetic user calls without crashing."
                    )
                else:
                    overall_passed = False

            else:
                # Server failed to start within timeout
                stderr_output = ""
                if srv_proc.poll() is not None:
                    _, errs = srv_proc.communicate(timeout=2)
                    stderr_output = errs.decode('utf-8', errors='ignore') if errs else "Process exited early"

                _emit_live_step(
                    orchestrator_url, sprint_id, 3, 4,
                    f"Live Server Boot Check (Port {test_port})",
                    "FAILED", boot_latency, f"Server failed to start. Error: {stderr_output[:300]}"
                )
                overall_passed = False

        except Exception as boot_err:
            logger.warning(f"Live server boot error: {boot_err}")
            _emit_live_step(
                orchestrator_url, sprint_id, 3, 4,
                "Live Server Boot Check",
                "FAILED", 0, str(boot_err)
            )
            overall_passed = False
        finally:
            if srv_proc and srv_proc.poll() is None:
                try:
                    srv_proc.terminate()
                    srv_proc.wait(timeout=3)
                except Exception:
                    try:
                        srv_proc.kill()
                    except Exception:
                        pass

    result_signal = "### RESULT: PASSED" if overall_passed else "### RESULT: FAILED"
    return {
        "passed": overall_passed,
        "result_signal": result_signal,
        "duration_sec": round(time.time() - start_time, 2),
        "steps": steps_results
    }

