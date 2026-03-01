FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium + 시스템 의존성 자동 설치 (ARM64 호환)
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "-m", "earnings_call_agent.main"]
