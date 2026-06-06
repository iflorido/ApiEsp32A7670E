FROM python:3.12-slim

WORKDIR /code

# Dependencias primero (cache de capas)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# El volumen /data guarda el .db de SQLite, persistente entre reinicios.
# Se crea con permisos abiertos para que el contenedor pueda escribir el .db
# aunque el volumen del host lo monte otro usuario.
RUN mkdir -p /data && chmod 777 /data
VOLUME ["/data"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]