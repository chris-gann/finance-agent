FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory for persistent storage
RUN mkdir -p /data

# Expose port (Railway sets PORT env var)
EXPOSE 5001

# Run the application
CMD ["python", "run.py"]
