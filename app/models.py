"""
Modelos de base de datos (SQLModel sobre SQLite).
Un unico archivo .db persistido en un volumen Docker.
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class Device(SQLModel, table=True):
    """Dispositivo ESP32. Preparado para multi-dispositivo aunque ahora haya uno."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    token: str = Field(index=True)                 # X-Device-Token para autenticar
    last_seen: Optional[datetime] = None           # ultimo poll/report
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Command(SQLModel, table=True):
    """Cola de comandos pendientes de ejecutar por el ESP."""
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(index=True, foreign_key="device.id")
    command: str                                   # status, gps, motor_on, ...
    args: Optional[str] = None                     # "3 90 CCW" por ejemplo
    status: str = Field(default="pending", index=True)  # pending|sent|done|error
    origin: str = Field(default="telegram")        # telegram|web|sms
    chat_id: Optional[int] = None                  # a quien responder en Telegram
    result: Optional[str] = None                   # respuesta del ESP
    created_at: datetime = Field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None


class Telemetry(SQLModel, table=True):
    """Cada reporte JSON que envia el ESP. Alimenta el dashboard."""
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(index=True, foreign_key="device.id")
    csq: Optional[int] = None                      # 0-31, calidad de senal
    rssi_dbm: Optional[int] = None                 # convertido a dBm
    operator: Optional[str] = None                 # nombre del operador
    network_type: Optional[str] = None             # LTE, GSM, etc.
    motor_busy: Optional[bool] = None
    motor_last_action: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    gps_fix: Optional[bool] = None
    free_heap: Optional[int] = None                # RAM libre (bytes)
    uptime_s: Optional[int] = None
    raw_json: Optional[str] = None                 # JSON completo por si acaso
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SmsLog(SQLModel, table=True):
    """Registro de SMS enviados/recibidos con coste."""
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: Optional[int] = Field(default=None, index=True)
    direction: str                                 # sent|received
    number: str
    text: str
    cost_eur: float = Field(default=0.0)           # 0.18 por SMS enviado
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BotMessage(SQLModel, table=True):
    """Historial de interacciones del bot de Telegram."""
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True)
    username: Optional[str] = None
    direction: str                                 # in|out
    text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)