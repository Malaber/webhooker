FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /usr/sbin/nologin webhooker

COPY pyproject.toml README.md /app/
COPY webhooker /app/webhooker

RUN python -m pip install --upgrade pip \
    && python -m pip install .

USER webhooker
EXPOSE 9100
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["webhooker-api", "--config-dir", "/etc/webhooker/projects", "--host", "0.0.0.0", "--port", "9100"]
