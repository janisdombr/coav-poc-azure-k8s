FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY emulator.py .

# CONN_STR must be provided at runtime via environment variable
ENV CONN_STR=""

USER 10001

CMD ["python", "emulator.py"]
