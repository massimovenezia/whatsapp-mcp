FROM python:3.11-slim

WORKDIR /app

COPY . .

# Install uv
RUN pip install --no-cache-dir uv

# Install dependencies into system Python
RUN uv pip install --system -r requirements.txt

ENV PYTHONUNBUFFERED=1

# Render provides $PORT
CMD ["python", "main_http.py"]
