"""
ROSClaw FastAPI Gateway

ROSClaw'un kendi web arayuzunun baglandigi tek giris noktasi
(harici uygulama/Telegram YOK - kendi sohbet arayuzumuz).
Hicbir logic icermez, sadece iletir.
"""

import asyncio
import json
import time
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import uvicorn

from core.agent_core import AgentCore
from tools.search_docs import search_docs
from tools.web_tools import web_search
from tools.discovery import scan_for_robots
from memory.robot_profiles import ROBOT_PRESETS

app = FastAPI(title="ROSClaw Gateway", version="1.0.0")
agent = AgentCore()
agent.tools.connect()
log_subscribers = []


class CommandRequest(BaseModel):
    instruction: str


class SearchRequest(BaseModel):
    query: str
    use_web: bool = False


class AddRobotRequest(BaseModel):
    name: str
    host: str
    port: int = 9090
    robot_type: str = "generic"
    velocity_limits: dict | None = None
    topic_allowlist: dict | None = None
    notes: str | None = None


@app.post("/command")
async def command(req: CommandRequest):
    """Robota komut gonder."""
    result = agent.run(req.instruction)
    await _broadcast_log({
        "type": "command_result",
        "instruction": req.instruction,
        "status": result["status"],
        "source": result.get("source"),
        "timestamp": time.time()
    })
    return result


@app.post("/search")
async def search(req: SearchRequest):
    """Teknik bilgi ara: once yerel RAG, istenirse (ve internet varsa) web."""
    if req.use_web:
        return web_search(req.query)
    return search_docs(req.query)


@app.get("/robots/presets")
async def robot_presets():
    """Bilinen robot tipleri icin hazir varsayilan ayarlar (dropdown icin)."""
    return {"presets": ROBOT_PRESETS}


@app.get("/robots/scan")
async def robots_scan():
    """
    Yerel agi tara, rosbridge calistiran cihazlari bul - WiFi'de 'ag ara'
    butonuna basmaya karsilik gelir. Robot markasi/modeli onemli degil,
    sadece rosbridge_websocket acik olmasi yeterli.
    """
    found = await asyncio.get_event_loop().run_in_executor(None, scan_for_robots)
    return {"found": found}


@app.get("/robots")
async def robots_list():
    """Kaydedilmis robot profillerini listele (WiFi'de bilinen aglar gibi)."""
    return {
        "profiles": agent.profile_store.list_profiles(),
        "active_id": agent.profile_store.active_id,
    }


@app.post("/robots")
async def robots_add(req: AddRobotRequest):
    """Yeni bir robot profili kaydet (elle ekleme - 'gizli ag' baglama gibi)."""
    preset = ROBOT_PRESETS.get(req.robot_type, ROBOT_PRESETS["generic"])
    profile = {
        "name": req.name,
        "host": req.host,
        "port": req.port,
        "robot_type": req.robot_type,
        "velocity_limits": req.velocity_limits or preset["velocity_limits"],
        "topic_allowlist": req.topic_allowlist or preset["topic_allowlist"],
        "movement_style": preset["movement_style"],
        "notes": req.notes if req.notes is not None else preset["notes"],
    }
    profile_id = agent.profile_store.add(profile)
    return {"status": "ok", "id": profile_id, "profile": profile}


@app.delete("/robots/{profile_id}")
async def robots_delete(profile_id: str):
    """Kaydedilmis bir robot profilini sil ('agi unut' gibi)."""
    deleted = agent.profile_store.delete(profile_id)
    return {"status": "ok" if deleted else "not_found"}


@app.post("/robots/{profile_id}/connect")
async def robots_connect(profile_id: str):
    """
    Baska bir robota gec - WiFi'de bir aga tiklayip baglanmak gibi. Mevcut
    baglantiyi keser, secilen profilin adresine baglanir, o robotun guvenlik
    limitlerini/izinli topic listesini devreye alir.
    """
    result = agent.switch_robot(profile_id)
    await _broadcast_log({
        "type": "robot_switch",
        "message": f"Robot degistirildi: {result.get('profile', {}).get('name', '?')} "
                    f"({'bagli' if result.get('connected') else 'baglanamadi'})",
        "timestamp": time.time(),
    })
    return result


@app.get("/robots/current")
async def robots_current():
    """Su an aktif olan robot profili ve baglanti durumu."""
    return {
        "profile": agent.active_profile,
        "connected": agent.tools._connected,
    }


@app.post("/stop")
async def stop():
    """E-stop - UI kapansa da calisir."""
    agent.emergency_stop()
    await _broadcast_log({"type": "estop", "timestamp": time.time()})
    return {"status": "stopped", "message": "E-stop aktif"}


@app.post("/estop/release")
async def release_estop():
    """E-stop kaldir."""
    agent.validator.release_estop()
    return {"status": "released"}


@app.get("/skills")
async def get_skills():
    """Ogrenilmis becerileri listele."""
    return {"skills": agent.skill_lib.list_skills(),
            "stats": agent.skill_lib.stats()}


@app.get("/status")
async def get_status():
    """Sistem durumu."""
    import os
    import requests as req
    ollama_ok = False
    try:
        r = req.get(f"{os.environ.get('OLLAMA_BASE_URL','http://localhost:11434')}/api/tags", timeout=2)
        ollama_ok = r.status_code == 200
    except Exception:
        pass
    return {
        "ollama": ollama_ok,
        "ros2": agent.tools._connected,
        "estop": agent.validator._estop_active,
        "skills": agent.skill_lib.stats()["total_skills"],
        "logs": len(agent.run_log),
        "robot_name": (agent.active_profile or {}).get("name"),
    }


@app.websocket("/logs")
async def websocket_logs(ws: WebSocket):
    """Canli audit log akisi."""
    await ws.accept()
    log_subscribers.append(ws)
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        log_subscribers.remove(ws)


async def _broadcast_log(data: dict):
    for ws in log_subscribers.copy():
        try:
            await ws.send_json(data)
        except Exception:
            log_subscribers.remove(ws)


@app.get("/", response_class=HTMLResponse)
async def web_ui():
    """Web arayuzunu sun."""
    ui_path = Path(__file__).parent / "web_ui.html"
    if ui_path.exists():
        return ui_path.read_text(encoding="utf-8")
    return "<h1>ROSClaw Gateway calisiyor</h1>"


if __name__ == "__main__":
    print("ROSClaw Gateway baslatiliyor...")
    print("Arayuz: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
