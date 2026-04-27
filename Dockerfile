FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PROJECT_RADAR_HOST=0.0.0.0
ENV PROJECT_RADAR_PORT=10000

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend

WORKDIR /app/backend

EXPOSE 10000

CMD ["python", "main.py"]
