# locusview runtime image.
#
# Its job in Phase 0 is to PROVE the real runtime: Python plus the genomics
# toolchain (HTSlib bgzip/tabix + bcftools) that Phase-1 ingest depends on. CI
# builds this on every PR so we never discover a missing system dependency
# halfway through a feature.
FROM python:3.11-slim-bookworm

# System dependencies: the genomics toolchain.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tabix bcftools ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# uv for fast, reproducible dependency installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (better layer caching). The package build needs the
# source tree and README, so copy those before syncing.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# Copy the rest of the project.
COPY . .

# Run as a non-root user.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

# Placeholder command for Phase 0; becomes the web server in Phase 1.
CMD ["uv", "run", "locusview"]
