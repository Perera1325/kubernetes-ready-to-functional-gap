# RFG application replica (Milestone 2-A). Build context: ../src   ->  docker build -f Dockerfiles/app.Dockerfile -t rfg-app:m2a src
# Base is pinned by TAG. The sha256 digest could not be resolved offline (registries unreachable from the authoring sandbox);
# run scripts/pin-digests.sh on a networked machine to append @sha256:... to the tag for strict reproducibility.
ARG PYTHON_IMAGE=python:3.13.1-slim-bookworm
FROM ${PYTHON_IMAGE}
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin rfg
WORKDIR /app
COPY application/app.py application/rfg_common.py /app/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8080 8081
ENTRYPOINT ["python", "/app/app.py"]
