# Vyro — wholesale billing desktop app (CustomTkinter + SQLite)
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# tkinter + X11 client libs + a font that has the ₹ glyph
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-tk \
        libx11-6 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Explicit list keeps Windows-only build files and local data out of the image.
COPY main.py db.py ui.py invoices.py printing.py sample_products.csv README.md ./

RUN useradd -m -u 1000 billbook && chown -R billbook:billbook /app
USER billbook

# The app writes its SQLite db + invoice PDFs under billbook_data/ (auto-created
# on first run). Mount /app/billbook_data as a volume so data survives rebuilds.
VOLUME ["/app/billbook_data"]

# GUI needs the host X server — see README "Run with Docker".
CMD ["python", "main.py"]
