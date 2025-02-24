#!/bin/bash

# 定义全局变量
PROJECT_DIR="/home/ubuntu/youtube-to-audio"
VENV_DIR="$PROJECT_DIR/venv"

# 检测上一步是否成功
check_success() {
    if [ $? -ne 0 ]; then
        echo "Error: $1 failed. Exiting..."
        exit 1
    else
        echo "$1 completed successfully."
    fi
}

# 更新系统包
update_system_packages() {
    echo "Updating system packages..."
    sudo apt-get update && sudo apt-get upgrade -y
    check_success "System package update"
}

# 安装必要工具
install_necessary_tools() {
    echo "Installing necessary tools..."
    sudo apt-get install -y \
        git \
        python3 \
        python3-pip \
        python3-venv \
        ffmpeg \
        openssh-client
    check_success "Installation of necessary tools"
}

# 安装 Docker 和 Docker Compose
install_docker_and_compose() {
    if ! command -v docker &> /dev/null; then
        echo "Docker not found. Installing Docker..."
        sudo apt-get install -y docker.io
        check_success "Docker installation"
    else
        echo "Docker already installed."
    fi

    if ! command -v docker-compose &> /dev/null; then
        echo "Docker Compose not found. Installing Docker Compose..."
        sudo curl -L "https://github.com/docker/compose/releases/download/v2.21.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
        sudo chmod +x /usr/local/bin/docker-compose
        check_success "Docker Compose installation"
    else
        echo "Docker Compose already installed."
    fi
}

# 克隆或更新代码仓库
clone_or_update_repo() {
    if [ ! -d "$PROJECT_DIR" ]; then
        echo "Project directory not found. Cloning repository..."
        git clone https://github.com/sunvolf/youtube-to-audio.git $PROJECT_DIR
        check_success "Repository cloning"
    else
        echo "Project directory exists. Pulling latest code..."
        cd $PROJECT_DIR
        # 检查是否有未提交的更改
        if [[ -n $(git status --porcelain) ]]; then
            echo "Local changes detected. Stashing changes to avoid conflicts..."
            git stash
            check_success "Stashing local changes"
        fi
        # 拉取最新代码
        git pull origin main
        check_success "Repository update"
    fi
}

# 设置项目目录权限
set_project_permissions() {
    echo "Setting project directory permissions..."
    sudo chown -R ubuntu:ubuntu $PROJECT_DIR
    sudo chmod -R 755 $PROJECT_DIR
    check_success "Project directory permission setup"
}

# 提示用户上传 .env 文件
upload_env_file() {
    if [ ! -f "$PROJECT_DIR/.env" ]; then
        echo "Please upload the .env file to the project directory: $PROJECT_DIR"
        read -p "Press Enter after uploading the .env file..."
        # 验证 .env 文件是否已上传
        if [ ! -f "$PROJECT_DIR/.env" ]; then
            echo "Error: .env file not found in $PROJECT_DIR. Please ensure it is uploaded."
            exit 1
        else
            echo ".env file uploaded successfully."
        fi
    else
        echo ".env file already exists. Skipping upload."
    fi
}

# 创建虚拟环境并安装依赖项
setup_virtualenv_and_dependencies() {
    if [ ! -d "$VENV_DIR" ]; then
        echo "Virtual environment not found. Creating virtual environment..."
        python3 -m venv $VENV_DIR
        check_success "Virtual environment creation"
    else
        echo "Virtual environment already exists. Skipping creation."
    fi

    echo "Installing Python dependencies..."
    source $VENV_DIR/bin/activate
    pip install --no-cache-dir -r $PROJECT_DIR/requirements.txt
    check_success "Dependency installation"
    deactivate
}

# 初始化数据库（覆盖安装）
initialize_database() {
    echo "Initializing database (covering existing data)..."
    source $VENV_DIR/bin/activate

    # 删除现有数据库内容
    python -c "
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

try:
    conn = psycopg2.connect(
        dbname='postgres',
        user=os.getenv('PGUSER'),
        password=os.getenv('PGPASSWORD'),
        host=os.getenv('PGHOST'),
        port=os.getenv('PGPORT', 5432),
        sslmode='require'
    )
    conn.autocommit = True
    cur = conn.cursor()
    
    # 删除现有数据库
    db_name = os.getenv('PGDATABASE')
    cur.execute(f'DROP DATABASE IF EXISTS \"{db_name}\"')
    logging.info(f'Database \"{db_name}\" dropped successfully.')

    # 重新创建数据库
    cur.execute(f'CREATE DATABASE \"{db_name}\"')
    logging.info(f'Database \"{db_name}\" created successfully.')
except Exception as e:
    logging.error(f'Failed to drop or create database: {e}')
    raise
finally:
    if 'cur' in locals():
        cur.close()
    if 'conn' in locals():
        conn.close()
"

    # 执行 init_db.py 初始化表结构
    python $PROJECT_DIR/init_db.py
    check_success "Database initialization"

    deactivate
}

# 构建并启动服务
build_and_start_services() {
    echo "Building and starting services..."
    cd $PROJECT_DIR
    docker-compose down && docker-compose up -d --build
    check_success "Docker service build and start"
}

# 主流程
main() {
    update_system_packages
    install_necessary_tools
    install_docker_and_compose
    clone_or_update_repo
    set_project_permissions
    upload_env_file
    setup_virtualenv_and_dependencies
    initialize_database
    build_and_start_services

    echo "Deployment complete! Access the web service at http://<your-ec2-public-ip>:5000"
}

# 执行主流程
main