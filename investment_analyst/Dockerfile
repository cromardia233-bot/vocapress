FROM python:3.11-slim

WORKDIR /app

# matplotlib 한국어 폰트
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium + 시스템 의존성 자동 설치 (ARM64 호환)
RUN playwright install --with-deps chromium

# matplotlib 폰트 캐시 갱신
RUN python -c "import matplotlib; matplotlib.font_manager._load_fontmanager(try_read_cache=False)"

COPY . .

# 데이터 영속화 디렉토리 (COPY 이후 생성하여 덮어쓰기 방지)
RUN mkdir -p /app/data

CMD ["python", "-m", "investment_analyst.main"]
