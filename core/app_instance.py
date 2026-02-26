from fastapi import FastAPI
import socketio

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins="*")
f_app = FastAPI(title="HAS-AI-TEAM Orchestrator")
sio_app = socketio.ASGIApp(sio, f_app)
