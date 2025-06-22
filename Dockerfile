FROM python:3.11-slim

ARG UID=1000
ARG GID=1000
ENV UID=${UID}
ENV GID=${GID}

RUN groupadd -g $GID appgroup && \
    useradd -m -u $UID -g appgroup appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN chown -R appuser:appgroup /app

USER appuser

CMD ["python", "tagWorker.py"]
