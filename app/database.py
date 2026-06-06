"""
Configuracion central y conexion a la base de datos SQLite.
Variables sensibles via entorno (.env / docker-compose).
"""
import os
from sqlmodel import SQLModel, create_engine, Session

# ── Configuracion via entorno ────────────────────────────────
# El archivo .db vive en un volumen montado para persistir entre reinicios.
DB_PATH       = os.getenv("DB_PATH", "/data/esp7670.db")
DEVICE_TOKEN  = os.getenv("DEVICE_TOKEN", "cambia-este-token-secreto")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")          # token del BotFather
TELEGRAM_ALLOWED_CHAT = os.getenv("TELEGRAM_ALLOWED_CHAT", "")  # tu chat_id
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "webhook-secreto")  # valida Telegram
PUBLIC_URL    = os.getenv("PUBLIC_URL", "https://esp7670.automaworks.es")
SMS_COST_EUR  = float(os.getenv("SMS_COST_EUR", "0.18"))
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "admin")

# SQLite con modo WAL para mejor concurrencia lectura/escritura.
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)


def init_db() -> None:
    """Crea el directorio y las tablas, y activa WAL. Idempotente."""
    # Asegura que el directorio del .db existe y es escribible. En Plesk el
    # volumen montado en /data puede no existir como ruta o no tener permisos.
    db_dir = os.path.dirname(DB_PATH) or "."
    try:
        os.makedirs(db_dir, exist_ok=True)
    except PermissionError:
        raise RuntimeError(
            f"No se puede crear el directorio '{db_dir}'. Revisa los permisos "
            f"del volumen montado en el contenedor (debe ser escribible)."
        )
    if not os.access(db_dir, os.W_OK):
        raise RuntimeError(
            f"El directorio '{db_dir}' no es escribible por el usuario del "
            f"contenedor. En Plesk, ajusta los permisos del volumen o monta "
            f"uno que el contenedor pueda escribir."
        )
    SQLModel.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        conn.exec_driver_sql("PRAGMA synchronous=NORMAL;")


def get_session():
    with Session(engine) as session:
        yield session