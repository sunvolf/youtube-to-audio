# 基础镜像
FROM python:3.9-slim

# 安装系统依赖（如 FFmpeg）
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY . /app

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 暴露端口（仅适用于 Web 服务）
EXPOSE 5000

# 启动命令（Web 服务）
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]