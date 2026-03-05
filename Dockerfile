FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY expert_service/ expert_service/

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "expert_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
