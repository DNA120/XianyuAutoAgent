FROM mcr.microsoft.com/playwright:latest

WORKDIR /app

RUN apt-get update && apt-get install -y python3 python3-pip && \
    pip3 install playwright flask loguru websockets requests python-dotenv openai && \
    rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 5000

CMD ["python3", "app.py"]
