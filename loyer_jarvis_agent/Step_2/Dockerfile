FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright and PostgreSQL
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p logs

# Copy models from Step 1 (adjust path as needed)
COPY ../Step_1/models.py ./models_step1.py

# Expose port for potential API (future)
EXPOSE 8000

# Default command
CMD ["python", "scraper_run.py"]
