# Hardened image for the Tethricor mutating admission webhook.
FROM python:3.12-slim

# Non-root runtime user.
RUN useradd --uid 1001 --create-home --shell /usr/sbin/nologin tethricor

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .

USER 1001
EXPOSE 8443
CMD ["python", "app.py"]
