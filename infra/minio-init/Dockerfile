FROM python:3.14.9-slim
RUN pip install --no-cache-dir minio==7.2.20
COPY init.py /init.py
USER 65534
ENTRYPOINT ["python", "/init.py"]
