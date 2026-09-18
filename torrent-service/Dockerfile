FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
# ffmpeg only: libtorrent comes from the PyPI manylinux wheel, which bundles its
# own libtorrent-rasterbar. The Debian python3-libtorrent package builds against the
# system python (3.13) and cannot be imported by this image's python 3.12.
RUN apt-get update && apt-get install -y --no-install-recommends \
	ffmpeg \
	&& rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
