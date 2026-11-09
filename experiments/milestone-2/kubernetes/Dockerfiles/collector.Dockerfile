# In-cluster collector / experiment driver. Build: docker build -f Dockerfiles/collector.Dockerfile -t rfg-collector:m2a src
ARG PYTHON_IMAGE=python:3.13.1-slim-bookworm
FROM ${PYTHON_IMAGE}
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin rfg && mkdir /results && chown 10001 /results
WORKDIR /app
COPY application/rfg_common.py /app/application/rfg_common.py
COPY collector.py kube.py client.py observer.py /app/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
ENTRYPOINT ["python", "/app/collector.py"]
