FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY sample_osm*.json.gz ./
COPY src ./src

RUN pip install --no-cache-dir requests ephem rsplan pyproj shapely 'paho-mqtt>=2.1' 'opening-hours-py>=2.1,<3'

ENV PYTHONPATH=/app/src

EXPOSE 8765

CMD ["python", "-m", "theroadragetrip.server", "--host", "0.0.0.0", "--preset", "Oulu", "--use-sample", "--no-auto-fetch", "--port", "8765", "--tick-rate", "30"]
