FROM python:3.10-slim

WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .

# 安装依赖（先安装flask确保存在）
RUN pip install --no-cache-dir flask==3.1.0 && \
    pip install --no-cache-dir openai==1.65.5 websockets==13.1 loguru==0.7.3 python-dotenv==1.0.1 requests==2.32.3

# 复制应用代码
COPY . .

EXPOSE 5000

CMD ["python", "app.py"]