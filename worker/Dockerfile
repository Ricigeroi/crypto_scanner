FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY fetcher.py worker.py .
CMD ["python", "worker.py"]
