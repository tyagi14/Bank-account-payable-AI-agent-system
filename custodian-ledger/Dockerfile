FROM python:3.14.9-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 app
COPY schema.sql .
COPY app app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=10 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
