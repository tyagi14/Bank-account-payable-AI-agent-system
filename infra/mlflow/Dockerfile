FROM ghcr.io/mlflow/mlflow:v3.17.2
RUN pip install --no-cache-dir "psycopg[binary]==3.3.6" \
 && useradd --uid 10001 --create-home mlflow \
 && mkdir -p /mlartifacts && chown mlflow /mlartifacts
USER mlflow
