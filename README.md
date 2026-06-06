# ESP7670 Control API

API en FastAPI para controlar y monitorizar un dispositivo **ESP32-S3 + A7670E (4G) + TMC2209**.
Recibe ordenes via **bot de Telegram** (sobre datos 4G, sin coste de SMS) y muestra toda la
telemetria en un **dashboard web**. Mantiene compatibilidad con el control por SMS existente
y lleva un registro del gasto en SMS.

Desplegada en VPS con Docker, detras de un reverse proxy en `https://esp7670.automaworks.es`.

---

## Estructura del repositorio

```
.
├── .github/
│   └── workflows/
│       └── docker-publish.yml     # CI/CD: build + push a ghcr.io
├── app/
│   ├── main.py                    # App FastAPI y endpoints
│   ├── models.py                  # Modelos SQLModel (tablas)
│   ├── database.py                # Conexion SQLite + config por entorno
│   ├── telegram.py                # Cliente de Telegram (envio de mensajes)
│   └── templates/
│       └── dashboard.html         # Panel web
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

> **Importante:** los archivos `.py` y el `dashboard.html` **deben** ir dentro de `app/`
> (y el HTML en `app/templates/`). El `Dockerfile` hace `COPY app ./app` y el arranque es
> `uvicorn app.main:app`, que depende de los imports relativos del paquete `app`. Si se
> colocan en la raiz, el contenedor no arranca.

---

## Variables de entorno

Son **las mismas que aparecen en `docker-compose.yml`**. Si despliegas pasando las variables
directamente al contenedor (sin archivo `.env`), tienes que definir estas:

| Variable                | Obligatoria | Ejemplo / valor                          | Descripcion |
|-------------------------|-------------|------------------------------------------|-------------|
| `DB_PATH`               | No          | `/data/esp7670.db`                       | Ruta del archivo SQLite. Debe apuntar al volumen montado. Por defecto `/data/esp7670.db`. |
| `DEVICE_TOKEN`          | **Si**      | `a1b2c3...` (24+ bytes)                   | Token secreto que el ESP envia en la cabecera `X-Device-Token`. Genera uno con `openssl rand -hex 24`. |
| `TELEGRAM_TOKEN`        | **Si**      | `123456789:AAxxxx...`                     | Token del bot que da @BotFather. |
| `TELEGRAM_ALLOWED_CHAT` | **Si**      | `123456789`                              | Tu `chat_id`. Unico chat autorizado a dar ordenes. Obtenlo con @userinfobot. |
| `WEBHOOK_SECRET`        | **Si**      | `f0e1d2...` (16+ bytes)                   | Secreto que Telegram reenvia en cada update para verificar el webhook. `openssl rand -hex 16`. |
| `PUBLIC_URL`            | **Si**      | `https://esp7670.automaworks.es`         | URL publica de la API. Se usa para registrar el webhook de Telegram. |
| `DASHBOARD_USER`        | **Si**      | `admin`                                  | Usuario del dashboard (Basic Auth). |
| `DASHBOARD_PASS`        | **Si**      | `una-contrasena-fuerte`                  | Contrasena del dashboard (Basic Auth). |
| `SMS_COST_EUR`          | No          | `0.18`                                   | Coste por SMS enviado, para el contador de gasto. Por defecto `0.18`. |

> Las variables marcadas como "No obligatoria" tienen valor por defecto en el codigo, pero
> conviene fijarlas. Las obligatorias **deben** definirse o la seguridad y el bot no funcionaran.

### Generar tokens seguros

```bash
openssl rand -hex 24   # DEVICE_TOKEN
openssl rand -hex 16   # WEBHOOK_SECRET
```

---

## Despliegue

### En el VPS con Plesk (metodo principal)

Plesk monta el contenedor desde su propia interfaz y **no lee el `docker-compose.yml`**.
Ese archivo sirve aqui como documentacion (que variables, que puerto, que volumen) y para
pruebas locales. En Plesk, al crear el contenedor desde la imagen de GHCR:

1. **Imagen:** `ghcr.io/<tu-usuario>/<tu-repo>:latest`.
2. **Puerto:** mapea el `8000` del contenedor al `8017` del host (o al que prefieras).
3. **Volumen:** crea un volumen y montalo en la ruta **`/data`** del contenedor. Aqui se
   guarda `esp7670.db`; mientras el montaje apunte a `/data`, el `.db` sobrevive a cada
   recreacion del contenedor (no se pierde al actualizar).
4. **Variables de entorno:** anade manualmente todas las de la tabla de arriba con sus
   valores reales. Deja `DB_PATH=/data/esp7670.db` para que use el volumen.
5. Apunta el dominio `esp7670.automaworks.es` (reverse proxy de Plesk) al puerto del host.

> El `docker-compose.yml` del repo lista las variables con sintaxis de solo-nombre
> (sin valores), precisamente para no subir secretos al repositorio. Los valores viven
> solo en Plesk.

### Pruebas locales (opcional, con docker compose)

Para probar en tu maquina, exporta las variables en la shell y levanta:

```bash
export DEVICE_TOKEN=... TELEGRAM_TOKEN=... TELEGRAM_ALLOWED_CHAT=... \
       WEBHOOK_SECRET=... PUBLIC_URL=https://esp7670.automaworks.es \
       DASHBOARD_USER=admin DASHBOARD_PASS=... DB_PATH=/data/esp7670.db
docker compose up -d --build
```

### CI/CD (GHCR)

Cada push a `main`/`master` construye y publica la imagen en
`ghcr.io/<tu-usuario>/<tu-repo>:latest`. En Plesk, tras un cambio, vuelve a desplegar
el contenedor tirando de la nueva imagen `:latest`. El volumen `/data` conserva la BD.

### Registrar el webhook de Telegram (una sola vez)

Tras desplegar y tener el dominio con HTTPS activo, registra el webhook:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_TOKEN>/setWebhook" \
  -d "url=https://esp7670.automaworks.es/telegram/webhook" \
  -d "secret_token=<WEBHOOK_SECRET>"
```

Comprueba con:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_TOKEN>/getWebhookInfo"
```

---

## Endpoints

### Para el ESP32 (autenticados con cabecera `X-Device-Token`)

| Metodo | Ruta           | Descripcion |
|--------|----------------|-------------|
| GET    | `/api/poll`    | El ESP pregunta si hay un comando pendiente. Devuelve `{id, command, args}` o `{command: null}`. |
| POST   | `/api/report`  | El ESP envia telemetria (senal, operador, motor, GPS, RAM, uptime...). |
| POST   | `/api/result`  | El ESP confirma el resultado de un comando. La API lo reenvia a Telegram. |
| POST   | `/api/sms`     | El ESP registra un SMS enviado/recibido (para el contador de gasto). |

### Telegram

| Metodo | Ruta                  | Descripcion |
|--------|-----------------------|-------------|
| POST   | `/telegram/webhook`   | Recibe los mensajes del bot. Verifica el secreto y el chat autorizado. |

### Dashboard (Basic Auth)

| Metodo | Ruta              | Descripcion |
|--------|-------------------|-------------|
| GET    | `/`               | Panel web. |
| GET    | `/api/dashboard`  | Datos JSON del panel. |
| POST   | `/api/command`    | Encola un comando desde el propio panel. |
| GET    | `/health`         | Healthcheck (sin auth). |

---

## Comandos soportados

Los mismos que la version SMS, mas los nuevos:

```
/status      -> estado del dispositivo
/gps         -> posicion GPS actual
/reiniciar   -> reinicia el dispositivo
/motor_on    -> mueve el motor (admite argumentos: /motor_on 3 90 CCW)
/motor_off   -> detiene/desactiva el motor
```

---

## Contrato JSON del ESP

### `POST /api/report` (telemetria)

```json
{
  "csq": 21,
  "rssi_dbm": -71,
  "operator": "Movistar",
  "network_type": "LTE",
  "motor_busy": false,
  "motor_last_action": "3 rev @ 90 RPM CCW",
  "gps_lat": 36.6,
  "gps_lon": -6.23,
  "gps_fix": true,
  "free_heap": 210000,
  "uptime_s": 3600
}
```

### `POST /api/result` (resultado de un comando)

```json
{ "id": 1, "ok": true, "result": "OK: 3 rev @ 90 RPM CCW" }
```

### `POST /api/sms` (registro de SMS)

```json
{ "direction": "sent", "number": "+34671637940", "text": "OK motor" }
```

> El coste solo se contabiliza para `direction: "sent"`, en el momento del `+CMGS`
> (la red ya lo factura aunque el destinatario no lo reciba).

---

## Notas tecnicas

- **Base de datos:** SQLite en modo WAL, en el volumen `esp7670-data` montado en `/data`.
  Persiste entre reinicios del contenedor.
- **Seguridad:** TLS de transporte (tu dominio) + token de aplicacion (`X-Device-Token`).
  El bot filtra por `chat_id`. El dashboard usa Basic Auth.
- **El ESP solo habla con esta API**, nunca directamente con Telegram. El VPS hace de puente.