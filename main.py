from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import json

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Менеджер соединений
class ConnectionManager:
    def __init__(self):
        # Словарь: {room_id: {client_id: websocket}}
        self.active_connections: dict[str, dict[str, WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_id: str, client_id: str):
        await websocket.accept()
        if room_id not in self.active_connections:
            self.active_connections[room_id] = {}
        self.active_connections[room_id][client_id] = websocket

    def disconnect(self, room_id: str, client_id: str):
        if room_id in self.active_connections:
            self.active_connections[room_id].pop(client_id, None)
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def broadcast_to_others(self, message: dict, room_id: str, sender_id: str):
        """Отправляет сообщение всем в комнате, кроме отправителя"""
        if room_id in self.active_connections:
            for client_id, connection in self.active_connections[room_id].items():
                if client_id != sender_id:
                    await connection.send_text(json.dumps(message))

manager = ConnectionManager()

@app.get("/", response_class=HTMLResponse)
async def get(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.websocket("/ws/{room_id}/{client_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str, client_id: str):
    await manager.connect(websocket, room_id, client_id)
    
    # 1. Собираем список тех, кто УЖЕ в комнате (кроме нас самих)
    existing_users = []
    if room_id in manager.active_connections:
        existing_users = [cid for cid in manager.active_connections[room_id] if cid != client_id]

    # 2. Отправляем этот список ТОЛЬКО подключившемуся пользователю
    if existing_users:
        await websocket.send_text(json.dumps({
            "type": "existing-users", 
            "payload": {"users": existing_users}
        }))

    # 3. Сообщаем остальным, что мы пришли (как было раньше)
    await manager.broadcast_to_others(
        {"type": "user-joined", "payload": {"clientId": client_id}}, 
        room_id, 
        client_id
    )

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Пересылаем WebRTC сигналы конкретному клиенту или всем
            target_id = message.get("target")
            
            if target_id:
                # Если указана цель, отправляем только ей
                connections = manager.active_connections.get(room_id, {})
                if target_id in connections:
                    await connections[target_id].send_text(json.dumps({
                        "type": message["type"],
                        "payload": message["payload"],
                        "sender": client_id
                    }))
            else:
                # Иначе бродкаст (обычно не используется для offer/answer, но может пригодиться)
                pass

    except WebSocketDisconnect:
        manager.disconnect(room_id, client_id)
        await manager.broadcast_to_others(
            {"type": "user-left", "payload": {"clientId": client_id}}, 
            room_id, 
            client_id
        )
