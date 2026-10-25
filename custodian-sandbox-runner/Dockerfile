FROM docker:29.9.2-cli AS cli

FROM python:3.14.9-slim
COPY --from=cli /usr/local/bin/docker /usr/local/bin/docker
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
# Runs as root only to use the mounted Docker socket; all capabilities are dropped in compose.
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=10 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
