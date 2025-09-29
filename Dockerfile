FROM python:3.11-slim

# Ensure predictable Python behavior
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create and use a non-root user
RUN groupadd -r app && useradd -r -g app app

# Copy application code
COPY . .

RUN mkdir -p /app/data /app/uploads /app/backups \
    && chown -R app:app /app \
    && chmod +x /app/entrypoint.sh

ARG PORT=5000
ENV PORT=${PORT}
ENV FLASK_APP=run.py
ENV FLASK_SKIP_CREATE_ALL=1
ENV DATABASE_PATH=/app/data/inventory.db

EXPOSE ${PORT}

# Run database migrations during the image build so freshly built
# containers always start with the latest schema. Running the command as the
# non-root application user mirrors how the application executes at runtime
# and ensures the generated SQLite database file has the correct ownership.
USER app
RUN flask db upgrade

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "-c", "gunicorn.conf.py", "run:app"]
