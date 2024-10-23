# Use Python 3.12 base image
FROM ubuntu:20.04

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file if necessary
COPY requirements.txt .

COPY entrypoint.sh /app/entrypoint.sh

## Install Python and pip
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3-pip \
    git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the rest of the application
COPY main.py /app/main.py

# Set the entry point for the action
ENTRYPOINT ["/app/entrypoint.sh"]
