# Ubuntu 26.04 ships Python 3.14 as python3. It does not publish a python3.12 package.
FROM ubuntu:26.04

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        git \
        ca-certificates \
    && python3 -m venv /opt/venv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:${PATH}"

RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY entrypoint.sh /app/entrypoint.sh
COPY main.py /app/main.py

RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
