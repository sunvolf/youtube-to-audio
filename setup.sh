#!/bin/bash

# 安装 Docker 和 Docker Compose
sudo apt-get update
sudo apt-get install -y docker.io docker-compose

# 克隆项目代码
git clone https://github.com/sunvolf/youtube-to-audio.git
cd youtube-converter

# 构建并启动服务
docker-compose up -d

echo "服务已启动！访问 http://localhost:5000"