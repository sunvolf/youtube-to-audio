#!/bin/bash

# 更新系统包
echo "Updating system packages..."
sudo apt-get update && sudo apt-get upgrade -y

# 安装必要的工具
echo "Installing necessary tools..."
sudo apt-get install -y \
    git \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    openssh-client

# 安装 Docker 和 Docker Compose
echo "Installing Docker and Docker Compose..."
if ! command -v docker &> /dev/null; then
    sudo apt-get install -y docker.io
fi

if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/download/v2.21.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
fi

# 克隆或更新代码仓库
PROJECT_DIR="/home/ubuntu/youtube-to-audio"
if [ ! -d "$PROJECT_DIR" ]; then
    echo "Cloning project repository..."
    git clone https://github.com/sunvolf/youtube-to-audio.git $PROJECT_DIR
else
    echo "Pulling latest code..."
    cd $PROJECT_DIR && git pull origin main
fi

# 设置项目目录权限，确保可以上传 .env 文件
echo "Setting project directory permissions..."
sudo chown -R ubuntu:ubuntu $PROJECT_DIR  # 确保 ubuntu 用户拥有项目目录的所有权限
sudo chmod -R 755 $PROJECT_DIR          # 设置目录权限为可读、可写、可执行

# 提示用户上传 .env 文件
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "Please upload the .env file to the project directory: $PROJECT_DIR"
    read -p "Press Enter after uploading the .env file..."

    # 验证 .env 文件是否已上传
    if [ ! -f "$PROJECT_DIR/.env" ]; then
        echo "Error: .env file not found in $PROJECT_DIR. Please ensure it is uploaded."
        exit 1
    fi
else
    echo ".env file already exists. Skipping upload."
fi

# 创建虚拟环境并安装依赖项
echo "Creating virtual environment and installing dependencies..."
cd $PROJECT_DIR
python3 -m venv venv
source venv/bin/activate
pip install --no-cache-dir -r requirements.txt
deactivate

# 初始化数据库
echo "Initializing database..."
source venv/bin/activate
python init_db.py
deactivate

# 构建并启动服务
echo "Building and starting services..."
docker-compose down && docker-compose up -d --build

# 提示部署完成
echo "Deployment complete! Access the web service at http://<your-ec2-public-ip>:5000"