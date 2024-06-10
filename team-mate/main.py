import uvicorn
import socketio
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from weaviate_utils import setup_weaviate_interface
from rag.agentic_rag import agent, query_with_fallback
import logging
import sys

sys.path.append('/home/mubarek/all_about_programing/Tenacious/TEAM-MATE/team-mate')

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# FastAPI application
app = FastAPI()

# Add CORS middleware to allow requests from any origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# SocketIO server
sio = socketio.AsyncServer(cors_allowed_origins="*", async_mode="asgi")

# Wrap with ASGI application, mounted on "/ws/socket.io"
socket_app = socketio.ASGIApp(sio, socketio_path="ws/socket.io")
app.mount("/ws", socket_app)

# Dictionary to store session data
sessions = {}

# Print {"Hello":"World"} on localhost:6789
@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_location = f"files/{file.filename}"
    with open(file_location, "wb+") as file_object:
        while content := await file.read(1024):  # read file chunk by chunk
            file_object.write(content)
    return {"info": f"file '{file.filename}' stored at location: '{file_location}'"}

@sio.on("connect")
async def connect(sid, environ):
    logger.debug(f"New Client Connected: {sid}")

@sio.on("disconnect")
async def disconnect(sid):
    logger.debug(f"Client Disconnected: {sid}")

@sio.on("connectionInit")
async def handle_connection_init(sid):
    logger.debug(f"Connection initialized for {sid}")
    await sio.emit("connectionAck", room=sid)

@sio.on("sessionInit")
async def handle_session_init(sid, data):
    logger.debug(f"Session {sid} initialized")
    session_id = data.get("sessionId")
    if session_id not in sessions:
        sessions[session_id] = []
    logger.debug(f"Session {session_id} initialized for {sid}, session data: {sessions[session_id]}")
    await sio.emit("sessionInit", {"sessionId": session_id, "chatHistory": sessions[session_id]}, room=sid)

@sio.on("textMessage")
async def handle_chat_message(sid, data):
    logger.debug(f"Message from {sid}: {data}")
    session_id = data.get("sessionId")
    if session_id:
        if session_id not in sessions:
            raise Exception(f"Session {session_id} not found")
        received_message = {
            "id": data.get("id"),
            "message": data.get("message"),
            "isUserMessage": True,
            "timestamp": data.get("timestamp"),
        }
        sessions[session_id].append(received_message)

        # Process the question using the query_with_fallback function
        question = data.get("message")
        answer = query_with_fallback(agent, question)

        response_message = {
            "id": data.get("id") + "_response",
            "textResponse": answer,
            "isUserMessage": False,
            "timestamp": data.get("timestamp"),
            "isComplete": True,
        }
        await sio.emit("textResponse", response_message, room=sid)
        sessions[session_id].append(response_message)

        logger.debug(f"Message from {sid} in session {session_id}: {data.get('message')}")
    else:
        logger.debug(f"No session ID provided by {sid}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=6789, lifespan="on", reload=True)