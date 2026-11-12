FROM python:3.13-alpine
RUN addgroup -g 10001 mailapp && adduser -D -u 10001 -G mailapp mailapp
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --only-binary=:all: -r /app/requirements.txt
COPY --chown=10001:10001 server.py /app/server.py
COPY --chown=10001:10001 mfa.py /app/mfa.py
COPY --chown=10001:10001 static /app/static
USER 10001:10001
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BIND=0.0.0.0 PORT=8787
EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=3)"
CMD ["python", "/app/server.py"]
