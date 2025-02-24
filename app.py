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
import logging
from dotenv import load_dotenv

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 加载环境变量
load_dotenv()

# 初始化Flask应用
app = Flask(__name__, static_folder='static', static_url_path='/static')
auth = HTTPBasicAuth()

# 导入数据库初始化函数
from init_db import get_db_connection, release_db_connection

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
    try:
        # 导入数据库初始化函数
        from init_db import initialize_connection_pool, init_db

        # 在应用启动时初始化数据库连接池和表结构
        initialize_connection_pool()
        init_db()
        app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))
    finally:
        if 'connection_pool' in globals():
            connection_pool.closeall()
            logging.info("Database connection pool closed.")