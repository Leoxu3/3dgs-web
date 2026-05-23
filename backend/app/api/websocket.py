"""Optional WebSocket route reserved for future streaming updates."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket


router = APIRouter()


@router.websocket("/ws")
async def websocket_status(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json(
        {
            "type": "status",
            "message": "WebSocket placeholder connected",
        }
    )
    await websocket.close()
