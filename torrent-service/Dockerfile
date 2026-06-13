# Debian's apt `python3-libtorrent` is a C-extension built for Debian's system
# Python. We base the image on Debian directly and run the app inside a venv
# created with --system-site-packages, so pip deps (fastapi, httpx, bs4, …) and
# the apt-provided libtorrent share one interpreter with a matching ABI.
FROM debian:trixie-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
	ffmpeg \
	python3 \
	python3-pip \
	python3-venv \
	libtorrent-rasterbar2.0 \
	python3-libtorrent \
	&& rm -rf /var/lib/apt/lists/*
RUN python3 -m venv --system-site-packages /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
