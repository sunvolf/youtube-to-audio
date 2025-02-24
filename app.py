"""
YouTube音频转换服务 - 主程序
整合Web服务器与Celery Worker功能
"""
import os
import uuid
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_httpauth import HTTPBasicAuth
import psycopg2
from psycopg2.extras import RealDictCursor
import logging

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 初始化Flask应用
app = Flask(__name__, static_folder='static', static_url_path='/static')
auth = HTTPBasicAuth()

# 数据库连接池
from psycopg2 import pool
try:
    connection_pool = pool.SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        dbname=os.getenv('PGDATABASE'),
        user=os.getenv('PGUSER'),
        password=os.getenv('PGPASSWORD'),
        host=os.getenv('PGHOST'),  # AWS RDS 主机名
        port=os.getenv('PGPORT', 5432),  # 默认端口为 5432
        sslmode='require'  # 使用 SSL 连接
    )
    logging.info("Database connection pool initialized successfully.")
except Exception as e:
    logging.error(f"Failed to initialize database connection pool: {e}")
    raise

def get_db_connection():
    return connection_pool.getconn()

def release_db_connection(conn):
    connection_pool.putconn(conn)

# 数据库初始化函数
def init_db():
    """
    初始化数据库表结构
    如果表已存在，则跳过初始化
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # 检查 api_keys 表是否存在
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'api_keys'
                );
            """)
            table_exists = cur.fetchone()[0]
            
            if not table_exists:
                # 创建 api_keys 表
                cur.execute("""
                    CREATE TABLE api_keys (
                        key TEXT PRIMARY KEY,
                        expiry_time TIMESTAMP NOT NULL
                    );
                """)
                logging.info("Table 'api_keys' created successfully.")
            else:
                logging.info("Table 'api_keys' already exists. Skipping initialization.")
        
        conn.commit()
    except Exception as e:
        logging.error(f"Failed to initialize database: {e}")
        conn.rollback()
        raise
    finally:
        release_db_connection(conn)

@auth.verify_password
def verify_password(username, password):
    """管理员界面身份验证"""
    return username == os.getenv('ADMIN_USER') and password == os.getenv('ADMIN_PASSWORD')

@app.route('/')
def index():
    """服务主页"""
    return "YouTube音频转换服务 - 访问 /admin 管理API密钥"

@app.route('/admin', methods=['GET', 'POST'])
@auth.login_required
def admin():
    """API密钥管理界面"""
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'generate':
            # 生成有效期180天的新密钥
            new_key = str(uuid.uuid4())
            expiry = datetime.now() + timedelta(days=180)
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        'INSERT INTO api_keys (key, expiry_time) VALUES (%s, %s)',
                        (new_key, expiry)
                    )
                conn.commit()
            finally:
                release_db_connection(conn)
        elif action == 'delete':
            # 删除指定密钥
            key = request.form.get('key')
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute('DELETE FROM api_keys WHERE key = %s', (key,))
                conn.commit()
            finally:
                release_db_connection(conn)
        return redirect(url_for('admin'))
    
    # 获取当前有效密钥列表
    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT key, expiry_time FROM api_keys WHERE expiry_time > NOW()')
            keys = cur.fetchall()
    finally:
        release_db_connection(conn)
    return render_template('admin.html', api_keys=keys)

@app.route('/convert', methods=['POST'])
def convert():
    """提交视频转换任务"""
    try:
        # 校验请求头
        if request.content_type != 'application/json':
            logging.error("Invalid Content-Type. Expected application/json.")
            return jsonify({'error': 'Invalid Content-Type. Expected application/json.'}), 400

        # API密钥验证
        api_key = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
        if not api_key:
            logging.error("Missing API key in request headers.")
            return jsonify({'error': 'Missing API key'}), 401
        
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT 1 FROM api_keys WHERE key = %s AND expiry_time > NOW()', (api_key,))
                if not cur.fetchone():
                    logging.error(f"Invalid or expired API key: {api_key}")
                    return jsonify({'error': 'Invalid or expired API key'}), 401
        finally:
            release_db_connection(conn)
        
        # URL格式校验
        youtube_url = request.json.get('youtube_url')
        if not youtube_url:
            logging.error("Missing 'youtube_url' field in request body.")
            return jsonify({'error': 'Missing "youtube_url" field in request body'}), 400
        if not re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/', youtube_url):
            logging.error(f"Invalid YouTube URL format: {youtube_url}")
            return jsonify({'error': 'Invalid YouTube URL format. Expected format: https://www.youtube.com/watch?v=...'}), 400
        
        # 提交异步任务
        from tasks import process_video
        task = process_video.delay(youtube_url)
        logging.info(f"Task submitted successfully. Task ID: {task.id}")
        return jsonify({
            'task_id': task.id,
            'status_url': f'/status/{task.id}'
        }), 202
    except Exception as e:
        logging.error(f"Error in /convert: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/status/<task_id>')
def get_status(task_id):
    """查询任务状态"""
    try:
        from tasks import process_video
        task = process_video.AsyncResult(task_id)
        return jsonify({
            'task_id': task.id,
            'status': task.state,
            'result': task.result if task.ready() else None
        })
    except Exception as e:
        logging.error(f"Error in /status: {e}")
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # 启动时初始化数据库并运行服务
    try:
        # 初始化数据库（仅在表不存在时执行）
        init_db()
        
        # 启动 Flask 应用
        app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))
    except Exception as e:
        logging.error(f"Failed to start application: {e}")
        raise