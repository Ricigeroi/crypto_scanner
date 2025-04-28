FROM python:3.11-slim

# system libs для OpenCV
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# копируем код и веса
COPY main.py .
COPY model ./model

EXPOSE 9100
CMD ["gunicorn", "-k", "gevent", "-b", "0.0.0.0:9100", "main:app"]
