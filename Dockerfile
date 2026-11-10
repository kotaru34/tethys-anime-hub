FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd -u 10001 -r -s /usr/sbin/nologin anime
COPY . /srv
RUN mkdir -p /state && chown anime:anime /state
USER anime
EXPOSE 3080
CMD ["uvicorn", "app.web:app", "--host", "0.0.0.0", "--port", "3080", "--proxy-headers"]
