FROM python:3.11-slim

WORKDIR /app

COPY . .

# Install uv
RUN pip install --no-cache-dir uv

# Install dependencies into system Python
RUN uv pip install --system -r requirements.txt

ENV PYTHONUNBUFFERED=1

# Render provides $PORT
CMD ["sh", "-c", "uv run main_http.py --host 0.0.0.0 --port ${PORT:-10000}"]
