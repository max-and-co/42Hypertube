FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Command is overridden in docker-compose, but good fallback:
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
