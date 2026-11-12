FROM python:3.11-slim
WORKDIR /srv
COPY app /srv/app
RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /srv
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz',timeout=3).status==200 else 1)"
CMD ["python", "-m", "app"]
