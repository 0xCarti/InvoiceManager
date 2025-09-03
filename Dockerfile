FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

ARG PORT=5000
ENV PORT=${PORT}
ENV FLASK_APP=run.py
ENV FLASK_SKIP_CREATE_ALL=1
ENV DATABASE_PATH=/app/data/inventory.db

EXPOSE ${PORT}

CMD ["sh", "-c", "flask db upgrade && gunicorn -k eventlet -w 1 run:app"]

