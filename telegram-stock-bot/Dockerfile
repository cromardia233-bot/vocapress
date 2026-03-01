FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 데이터 영속화 디렉토리 (DB + 세션 파일)
RUN mkdir -p /app/data

CMD ["python", "main.py"]
