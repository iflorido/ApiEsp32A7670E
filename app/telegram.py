"""
Cliente minimo de Telegram. El VPS es el unico que habla con la API de
Telegram; el ESP solo habla con nuestra API. Usamos httpx async.
"""
import httpx
from .database import TELEGRAM_TOKEN

API_BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


async def send_message(chat_id: int, text: str) -> bool:
    """Envia un mensaje de texto a un chat de Telegram."""
    if not TELEGRAM_TOKEN:
        return False
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(
                f"{API_BASE}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False


async def set_webhook(public_url: str, secret: str) -> bool:
    """Registra el webhook para recibir los mensajes del bot."""
    if not TELEGRAM_TOKEN:
        return False
    url = f"{public_url}/telegram/webhook"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{API_BASE}/setWebhook",
            json={"url": url, "secret_token": secret},
        )
        return r.status_code == 200