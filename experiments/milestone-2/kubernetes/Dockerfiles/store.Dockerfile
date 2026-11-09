# RFG dependency store (WAL replay + CRC + -LOADING + SCAN). Build: docker build -f Dockerfiles/store.Dockerfile -t rfg-store:m2a src
ARG PYTHON_IMAGE=python:3.13.1-slim-bookworm
FROM ${PYTHON_IMAGE}
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin rfg && mkdir /data && chown 10001 /data
WORKDIR /app
COPY application/store.py application/rfg_common.py /app/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 6380
ENTRYPOINT ["python", "/app/store.py"]
