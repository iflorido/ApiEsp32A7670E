FROM python:3.12-slim

WORKDIR /code

# Dependencias primero (cache de capas)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# El volumen /data guarda el .db de SQLite, persistente entre reinicios
VOLUME ["/data"]

EXPOSE 8017

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8017"]