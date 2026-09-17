FROM python:3.13-slim
WORKDIR /app
COPY src/ /app/src/
ENV PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "plan_review_bridge", "serve", "--exchange", "/exchange"]
