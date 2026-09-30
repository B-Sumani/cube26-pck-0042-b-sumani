# Pack Manager · Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY submissions/b-sumani/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy codebase
COPY submissions/b-sumani/ /app/submissions/b-sumani/

# Expose web port
EXPOSE 8000

# Run FastAPI via uvicorn
CMD ["uvicorn", "submissions.b-sumani.agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
