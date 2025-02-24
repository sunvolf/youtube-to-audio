# 使用官方Python镜像
FROM python:3.9-slim-buster

# 设置非root用户
RUN groupadd -r appuser && useradd -r -g appuser appuser
USER appuser

# 安装系统依赖
RUN sudo apt-get update && sudo apt-get install -y \
    ffmpeg \
    libpq-dev \
    && sudo rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 复制项目文件（通过.dockerignore过滤非必要文件）
COPY --chown=appuser:appuser . .

# 安装Python依赖
RUN pip install --no-cache-dir --user -r requirements.txt

# 环境变量
ENV PYTHONPATH=/app
ENV FLASK_APP=app.py

# 暴露端口
EXPOSE 5000

# 启动命令
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:app"]
