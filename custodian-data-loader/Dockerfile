FROM python:3.14.9-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home app && mkdir -p /cache/hf && chown -R app /cache
COPY loader loader
USER app
ENV HF_HOME=/cache/hf
ENTRYPOINT ["python", "-m", "loader.main"]
