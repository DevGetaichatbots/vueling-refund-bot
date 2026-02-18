FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .
RUN mkdir -p screenshots

ENV PORT=5000
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

EXPOSE 5000

CMD ["python", "main.py"]
