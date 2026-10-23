FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir selenium==4.29.0 tzdata==2025.1
COPY runner.py config.json ./
ENV PYTHONUNBUFFERED=1
CMD ["python", "runner.py", "schedule"]
