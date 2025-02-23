#!/bin/bash

# 更新系统包
echo "Updating system packages..."
sudo apt-get update && sudo apt-get upgrade -y

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

# 提示用户上传 .env 文件
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "Please upload the .env file to the project directory: $PROJECT_DIR"
    read -p "Press Enter after uploading the .env file..."
else
    echo ".env file already exists. Skipping upload."
fi

# 初始化数据库
echo "Initializing database..."
cd $PROJECT_DIR && python init_db.py

# 构建并启动服务
echo "Building and starting services..."
cd $PROJECT_DIR && docker-compose down && docker-compose up -d --build

# 提示部署完成
echo "Deployment complete! Access the web service at http://<your-ec2-public-ip>:5000"