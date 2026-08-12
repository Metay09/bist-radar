FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY config ./config
COPY migrations ./migrations
COPY alembic.ini ./
COPY tests/fixtures ./tests/fixtures
RUN pip install --no-cache-dir .
RUN useradd --create-home --uid 10001 radar && chown -R radar:radar /app
USER radar
EXPOSE 8765
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8765"]
