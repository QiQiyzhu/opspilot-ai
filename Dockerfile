FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements-lock.txt pyproject.toml ./
RUN pip install -r requirements-lock.txt
COPY backend ./backend
COPY evals ./evals
COPY analytics ./analytics
RUN pip install --no-deps -e . && useradd --create-home appuser && mkdir -p /app/model-cache && chown -R appuser /app
USER appuser
EXPOSE 8003
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8003"]
