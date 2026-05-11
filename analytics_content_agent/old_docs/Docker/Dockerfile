FROM ubuntu:24.04

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3 \
    python3-dev \
    python3-venv \
    python3-pip \
    python-is-python3 \
    libpq-dev \
    curl \
    ca-certificates \
    dos2unix \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

RUN python3 -m venv /opt/venv \
 && pip install --upgrade pip setuptools wheel \
 && pip install -r requirements.txt \
 && pip install pandas numpy matplotlib statsmodels scipy

COPY . /app

COPY Docker/entrypoint.sh /entrypoint.sh
RUN dos2unix /entrypoint.sh && chmod +x /entrypoint.sh

EXPOSE 8000

CMD ["/entrypoint.sh"]