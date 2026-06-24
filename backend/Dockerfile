FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY main.py .

# OWASP Container Security: out from root user in the Pod
USER 10001

CMD ["python", "main.py"]