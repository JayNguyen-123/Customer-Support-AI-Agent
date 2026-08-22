# =====================================================================
# Stage 1: Build & Dependency Collection Compilation Arena
# =====================================================================
FROM python:3.11-slim AS builder

WORKDIR /app

# Install native system build requirements needed to compile performance libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Optimize layer caching behavior by loading dependency arrays first
COPY requirements.txt .

# Compile and dump installed wheel sets into the isolated local user profile bin
RUN pip install --no-cache-dir --user -r requirements.txt

# =====================================================================
# Stage 2: Final Lightweight Runner Deployment Image Canvas
# =====================================================================
FROM python:3.11-slim AS runner

WORKDIR /app

# Copy the pre-compiled dependency arrays out of the staging builder tier
COPY --from=builder /root/.local /root/.local

# Pull down your operational project directory files
COPY . .

# Ensure compiled user space package dependencies are appended to the system PATH
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1

# FastAPI's operational network endpoint gate portal
EXPOSE 8000

# Make our initialization runtime automation shell script executable
RUN chmod +x entrypoint.sh

# Delegate structural initialization and startup sequences to the entrypoint worker
ENTRYPOINT ["./entrypoint.sh"]
