# Launched once per OCR call by custodian-sandbox-runner; never a long-running service.
FROM python:3.14.9-slim
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir nono-py==0.16.0 \
 && useradd --uid 10001 --no-create-home ocr
COPY entry.py /opt/ocr/entry.py
USER 10001
ENTRYPOINT ["python", "/opt/ocr/entry.py"]
