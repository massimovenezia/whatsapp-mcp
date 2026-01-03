FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install uv
RUN uv pip install -r requirements.txt

ENV PYTHONUNBUFFERED=1

CMD ["python", "main_http.py"]
