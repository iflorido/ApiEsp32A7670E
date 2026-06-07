"""
API FastAPI para el control del ESP32 + A7670E + TMC2209.

Endpoints principales:
  ESP32 (autenticado por X-Device-Token):
    GET  /api/poll        -> el ESP pregunta si hay comandos pendientes
    POST /api/report      -> el ESP envia telemetria (JSON)
    POST /api/result      -> el ESP confirma el resultado de un comando
    POST /api/sms         -> el ESP registra un SMS enviado/recibido

  Telegram:
    POST /telegram/webhook -> recibe los mensajes del bot

  Dashboard (Basic Auth):
    GET  /                 -> panel web
    GET  /api/dashboard    -> datos JSON para el panel
"""
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import (FastAPI, Depends, Header, HTTPException, Request,
                     status)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from contextlib import asynccontextmanager

from .database import (init_db, get_session, engine, DEVICE_TOKEN,
                       SMS_COST_EUR, TELEGRAM_ALLOWED_CHAT, WEBHOOK_SECRET,
                       PUBLIC_URL, DASHBOARD_USER, DASHBOARD_PASS)
from .models import Device, Command, Telemetry, SmsLog, BotMessage
from . import telegram

# Comandos soportados (los mismos que SMS + los nuevos)
KNOWN_COMMANDS = {
    "status", "gps", "reiniciar", "motor_on", "motor_off",
    "yellow_on", "yellow_off", "blue_on", "blue_off", "red_on", "red_off",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Asegura que existe el dispositivo por defecto
    with Session(engine) as s:
        dev = s.exec(select(Device)).first()
        if not dev:
            s.add(Device(name="esp32-principal", token=DEVICE_TOKEN))
            s.commit()
    yield


app = FastAPI(title="ESP7670 Control API", lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates")
security = HTTPBasic()


# ── Autenticacion del ESP por token ──────────────────────────
def auth_device(x_device_token: str = Header(default="")) -> Device:
    with Session(engine) as s:
        dev = s.exec(select(Device).where(Device.token == x_device_token)).first()
    if not dev or not secrets.compare_digest(x_device_token, DEVICE_TOKEN):
        raise HTTPException(status_code=401, detail="token invalido")
    return dev


# ── Autenticacion del dashboard (Basic Auth) ─────────────────
def auth_dashboard(creds: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(creds.username, DASHBOARD_USER)
    ok_pass = secrets.compare_digest(creds.password, DASHBOARD_PASS)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401, detail="no autorizado",
            headers={"WWW-Authenticate": "Basic"},
        )
    return creds.username


# ════════════════════════════════════════════════════════════
#  ENDPOINTS DEL ESP32
# ════════════════════════════════════════════════════════════

@app.get("/api/poll")
def poll(device: Device = Depends(auth_device),
         session: Session = Depends(get_session)):
    """El ESP pregunta si hay un comando pendiente. Devuelve uno (FIFO)."""
    device.last_seen = datetime.utcnow()
    session.add(device)

    cmd = session.exec(
        select(Command)
        .where(Command.device_id == device.id, Command.status == "pending")
        .order_by(Command.created_at)
    ).first()

    if not cmd:
        session.commit()
        return {"command": None}

    cmd.status = "sent"
    cmd.executed_at = datetime.utcnow()
    session.add(cmd)
    session.commit()
    session.refresh(cmd)
    return {
        "id": cmd.id,
        "command": cmd.command,
        "args": cmd.args or "",
    }


@app.post("/api/report")
async def report(request: Request,
                 device: Device = Depends(auth_device),
                 session: Session = Depends(get_session)):
    """El ESP envia telemetria periodica (senal, operador, motor, GPS...)."""
    data = await request.json()
    device.last_seen = datetime.utcnow()
    session.add(device)

    t = Telemetry(
        device_id=device.id,
        csq=data.get("csq"),
        rssi_dbm=data.get("rssi_dbm"),
        operator=data.get("operator"),
        network_type=data.get("network_type"),
        motor_busy=data.get("motor_busy"),
        motor_last_action=data.get("motor_last_action"),
        gps_lat=data.get("gps_lat"),
        gps_lon=data.get("gps_lon"),
        gps_fix=data.get("gps_fix"),
        free_heap=data.get("free_heap"),
        uptime_s=data.get("uptime_s"),
        led_yellow=data.get("led_yellow"),
        led_green=data.get("led_green"),
        led_red=data.get("led_red"),
        raw_json=json.dumps(data),
    )
    session.add(t)
    session.commit()
    return {"ok": True}


@app.post("/api/result")
async def result(request: Request,
                 device: Device = Depends(auth_device),
                 session: Session = Depends(get_session)):
    """El ESP confirma el resultado de un comando. Reenvia a Telegram."""
    data = await request.json()
    cmd_id = data.get("id")
    result_text = data.get("result", "")
    ok = data.get("ok", True)

    cmd = session.get(Command, cmd_id)
    if cmd:
        cmd.status = "done" if ok else "error"
        cmd.result = result_text
        cmd.executed_at = datetime.utcnow()
        session.add(cmd)
        session.commit()

        # Si el comando vino de Telegram, responder en el chat
        if cmd.origin == "telegram" and cmd.chat_id:
            msg = f"<b>{cmd.command}</b>\n{result_text}"
            await telegram.send_message(cmd.chat_id, msg)
            session.add(BotMessage(chat_id=cmd.chat_id, direction="out", text=msg))
            session.commit()
    return {"ok": True}


@app.post("/api/sms")
async def log_sms(request: Request,
                  device: Device = Depends(auth_device),
                  session: Session = Depends(get_session)):
    """El ESP registra un SMS enviado o recibido (para el log de gasto)."""
    data = await request.json()
    direction = data.get("direction", "sent")
    # Coste: solo los enviados cuentan, en el momento del +CMGS
    cost = SMS_COST_EUR if direction == "sent" else 0.0
    log = SmsLog(
        device_id=device.id,
        direction=direction,
        number=data.get("number", ""),
        text=data.get("text", ""),
        cost_eur=cost,
    )
    session.add(log)
    session.commit()
    return {"ok": True}


# ════════════════════════════════════════════════════════════
#  WEBHOOK DE TELEGRAM
# ════════════════════════════════════════════════════════════

@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    session: Session = Depends(get_session),
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    """Recibe mensajes del bot, valida el chat autorizado y encola comandos."""
    if not secrets.compare_digest(x_telegram_bot_api_secret_token, WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="webhook no valido")

    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    username = message["chat"].get("username", "")
    text = (message.get("text") or "").strip()

    # Filtrar por chat autorizado
    if TELEGRAM_ALLOWED_CHAT and str(chat_id) != str(TELEGRAM_ALLOWED_CHAT):
        await telegram.send_message(chat_id, "No autorizado.")
        return {"ok": True}

    session.add(BotMessage(chat_id=chat_id, username=username,
                           direction="in", text=text))
    session.commit()

    # Parsear comando: /motor_on 3 90 CCW
    if not text.startswith("/"):
        await telegram.send_message(chat_id, "Usa un comando, p.ej. /status")
        return {"ok": True}

    parts = text[1:].split()
    cmd_name = parts[0].lower()
    args = " ".join(parts[1:])

    if cmd_name not in KNOWN_COMMANDS:
        await telegram.send_message(
            chat_id,
            "Comandos: /status /gps /reiniciar /motor_on /motor_off")
        return {"ok": True}

    dev = session.exec(select(Device)).first()
    cmd = Command(device_id=dev.id, command=cmd_name, args=args,
                  origin="telegram", chat_id=chat_id, status="pending")
    session.add(cmd)
    session.commit()

    await telegram.send_message(
        chat_id, f"Comando <b>{cmd_name}</b> encolado. Esperando al dispositivo...")
    return {"ok": True}


# ════════════════════════════════════════════════════════════
#  DASHBOARD
# ════════════════════════════════════════════════════════════

@app.get("/api/dashboard")
def dashboard_data(user: str = Depends(auth_dashboard),
                   session: Session = Depends(get_session)):
    """Datos JSON que alimentan el panel web."""
    dev = session.exec(select(Device)).first()

    last_tel = session.exec(
        select(Telemetry).order_by(Telemetry.created_at.desc())
    ).first()

    recent_tel = session.exec(
        select(Telemetry).order_by(Telemetry.created_at.desc()).limit(50)
    ).all()

    recent_cmds = session.exec(
        select(Command).order_by(Command.created_at.desc()).limit(20)
    ).all()

    sms = session.exec(
        select(SmsLog).order_by(SmsLog.created_at.desc()).limit(50)
    ).all()

    total_cost = sum(s.cost_eur for s in sms)
    sms_sent = sum(1 for s in sms if s.direction == "sent")
    sms_recv = sum(1 for s in sms if s.direction == "received")

    # Estado online: visto en los ultimos 90s
    online = False
    if dev and dev.last_seen:
        online = (datetime.utcnow() - dev.last_seen) < timedelta(seconds=90)

    def tel_dict(t):
        return {
            "csq": t.csq, "rssi_dbm": t.rssi_dbm, "operator": t.operator,
            "network_type": t.network_type, "motor_busy": t.motor_busy,
            "motor_last_action": t.motor_last_action,
            "gps_lat": t.gps_lat, "gps_lon": t.gps_lon, "gps_fix": t.gps_fix,
            "free_heap": t.free_heap, "uptime_s": t.uptime_s,
            "led_yellow": t.led_yellow, "led_green": t.led_green, "led_red": t.led_red,
            "ts": t.created_at.isoformat(),
        }

    return {
        "device": {
            "name": dev.name if dev else "-",
            "online": online,
            "last_seen": dev.last_seen.isoformat() if dev and dev.last_seen else None,
        },
        "current": tel_dict(last_tel) if last_tel else None,
        "history": [tel_dict(t) for t in reversed(recent_tel)],
        "commands": [{
            "command": c.command, "args": c.args, "status": c.status,
            "origin": c.origin, "result": c.result,
            "ts": c.created_at.isoformat(),
        } for c in recent_cmds],
        "sms": {
            "total_cost": round(total_cost, 2),
            "sent": sms_sent, "received": sms_recv,
            "log": [{
                "direction": s.direction, "number": s.number,
                "text": s.text, "cost": s.cost_eur,
                "ts": s.created_at.isoformat(),
            } for s in sms],
        },
    }


@app.post("/api/command")
async def web_command(request: Request,
                      user: str = Depends(auth_dashboard),
                      session: Session = Depends(get_session)):
    """Permite enviar comandos desde el propio dashboard."""
    data = await request.json()
    cmd_name = data.get("command", "").lower()
    args = data.get("args", "")
    if cmd_name not in KNOWN_COMMANDS:
        raise HTTPException(status_code=400, detail="comando desconocido")
    dev = session.exec(select(Device)).first()
    cmd = Command(device_id=dev.id, command=cmd_name, args=args,
                  origin="web", status="pending")
    session.add(cmd)
    session.commit()
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, user: str = Depends(auth_dashboard)):
    return templates.TemplateResponse(request, "dashboard.html")


@app.get("/health")
def health():
    return {"status": "ok"}