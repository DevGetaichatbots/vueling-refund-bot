FROM python:3.11-slim

WORKDIR /app

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps

COPY . .
RUN mkdir -p screenshots

ENV PORT=5000
EXPOSE 5000

CMD ["python", "main.py"]
