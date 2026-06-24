FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Copy source first so `pip install .` can build the package, then keep the source
# on disk at /app (cwd wins over site-packages) so migration .sql files resolve.
COPY . .
RUN pip install --no-cache-dir .

EXPOSE 8000

# Apply migrations, then serve. Compose gates this on DB+Redis being healthy.
CMD ["sh", "-c", "python -m db.migrate && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
