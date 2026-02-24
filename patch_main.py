import re

with open('core/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add ProjectException model
if 'class ProjectException' not in content:
    model_code = """
class ProjectException(Base):
    __tablename__ = "project_exceptions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sprint_id = Column(String, index=True)
    source = Column(String)
    command = Column(String, nullable=True)
    error_message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)"""
    content = content.replace('Base.metadata.create_all(engine)', model_code)

# 2. Add log_project_exception function and update extract_files
if 'def log_project_exception' not in content:
    utils_addition = """
def log_project_exception(sprint_id: str, source: str, command: str, error_message: str):
    db = SessionLocal()
    try:
        db.add(ProjectException(
            sprint_id=sprint_id,
            source=source,
            command=command,
            error_message=error_message
        ))
        db.commit()
        # Broadcast the exception to UI via socketio
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(sio.emit("project_exception", {"sprint_id": sprint_id, "source": source}))
    except Exception as e:
        logger.error(f"Failed to log project exception: {e}")
    finally:
        db.close()

def extract_files(text: str, project_dir: str, sprint_id: str = None):"""
    content = content.replace('def extract_files(text: str, project_dir: str):', utils_addition)
    
    # Update install_dependencies call inside extract_files
    content = content.replace('install_dependencies(project_dir)', 'install_dependencies(project_dir, sprint_id)')

# 3. Update install_dependencies error handling
content = content.replace('def install_dependencies(project_dir: str):', 'def install_dependencies(project_dir: str, sprint_id: str = None):')
content = content.replace('logger.error(f"npm install failed for {project_dir}: {e}")', 
                         'logger.error(f"npm install failed for {project_dir}: {e}")\n            if sprint_id: log_project_exception(sprint_id, "install_dependencies", "npm install", str(e))')
content = content.replace('logger.error(f"pip install failed for {project_dir}: {e}")',
                         'logger.error(f"pip install failed for {project_dir}: {e}")\n            if sprint_id: log_project_exception(sprint_id, "install_dependencies", "pip install", str(e))')

# 4. Update execute_setup_commands error handling
content = content.replace('def execute_setup_commands(commands: List[str], project_dir: str):', 'def execute_setup_commands(commands: List[str], project_dir: str, sprint_id: str = None):')
# Add error logging for subprocess errors
if 'if sprint_id: log_project_exception(sprint_id, "execute_setup_commands", cmd, err_msg)' not in content:
    content = content.replace('logger.error(f"Command failed: {cmd}. Error: {err_msg}")',
                             'logger.error(f"Command failed: {cmd}. Error: {err_msg}")\n            if sprint_id: log_project_exception(sprint_id, "execute_setup_commands", cmd, err_msg)')
    content = content.replace('logger.error(f"Command execution error: {cmd}. Error: {e}")',
                             'logger.error(f"Command execution error: {cmd}. Error: {e}")\n            if sprint_id: log_project_exception(sprint_id, "execute_setup_commands", cmd, str(e))')

# 5. Add /exceptions API Endpoint
if '@app.get("/exceptions")' not in content:
    api_endpoint = """
@app.get("/exceptions")
def get_all_exceptions(db: Session = Depends(get_db)):
    exceptions = (
        db.query(ProjectException)
        .order_by(ProjectException.timestamp.desc())
        .limit(100)
        .all()
    )
    return {
        "exceptions": [
            {
                "id": e.id,
                "sprint_id": e.sprint_id,
                "source": e.source,
                "command": e.command,
                "error_message": e.error_message,
                "timestamp": e.timestamp.isoformat()
            }
            for e in exceptions
        ]
    }
"""
    # Insert before the chat history endpoints
    content = content.replace('# --- CHAT HISTORY ENDPOINTS ---', api_endpoint + '\n# --- CHAT HISTORY ENDPOINTS ---')

# 6. Update caller in llm_worker
content = content.replace('execute_setup_commands(plan["setup_commands"], target_dir)', 'execute_setup_commands(plan["setup_commands"], target_dir, sprint_id=sid)')
content = content.replace('extract_files(resp, target_dir)', 'extract_files(resp, target_dir, sprint_id=sid)')

# 7. Add Tester FAILED logging
if 'log_project_exception(sid, "Tester", "QA Verification", resp)' not in content:
    tester_code = """
            if agent == "Tester":
                if "FAILED" in resp.upper():
                    log_project_exception(sid, "Tester", "QA Verification", resp)
                    db = SessionLocal()"""
    content = content.replace("""
            if agent == "Tester":
                if "FAILED" in resp.upper():
                    db = SessionLocal()""", tester_code)

with open('core/main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Patch applied.")
