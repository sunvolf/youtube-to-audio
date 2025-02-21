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

app = Flask(__name__, static_folder='static', static_url_path='/static')
auth = HTTPBasicAuth()

# 数据库初始化函数
def init_db():
    """初始化数据库表结构（如果不存在）"""
    with psycopg2.connect(
        dbname=os.getenv('PGDATABASE'),
        user=os.getenv('PGUSER'),
        password=os.getenv('PGPASSWORD'),
        host=os.getenv('PGHOST'),
        port=os.getenv('PGPORT'),
        sslmode='prefer'
    ) as conn:
        with conn.cursor() as cur:
            # 创建API密钥表
            cur.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id SERIAL PRIMARY KEY,
                    key VARCHAR(36) UNIQUE NOT NULL,
                    expiry_time TIMESTAMPTZ NOT NULL
                )
            ''')
            # 创建任务记录表
            cur.execute('''
                CREATE TABLE IF NOT EXISTS conversions (
                    id SERIAL PRIMARY KEY,
                    task_id VARCHAR(255) UNIQUE NOT NULL,
                    youtube_id VARCHAR(11) NOT NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            ''')
            conn.commit()

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
            with psycopg2.connect(os.getenv('DATABASE_URL')) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        'INSERT INTO api_keys (key, expiry_time) VALUES (%s, %s)',
                        (new_key, expiry)
                    )
                conn.commit()
        elif action == 'delete':
            # 删除指定密钥
            key = request.form.get('key')
            with psycopg2.connect(os.getenv('DATABASE_URL')) as conn:
                with conn.cursor() as cur:
                    cur.execute('DELETE FROM api_keys WHERE key = %s', (key,))
                conn.commit()
        return redirect(url_for('admin'))
    
    # 获取当前有效密钥列表
    with psycopg2.connect(os.getenv('DATABASE_URL')) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT key, expiry_time FROM api_keys WHERE expiry_time > NOW()')
            keys = cur.fetchall()
    return render_template('admin.html', api_keys=keys)

@app.route('/convert', methods=['POST'])
def convert():
    """提交视频转换任务"""
    # API密钥验证
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
    if not api_key:
        return jsonify({'error': 'Missing API key'}), 401
    
    with psycopg2.connect(os.getenv('DATABASE_URL')) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM api_keys WHERE key = %s AND expiry_time > NOW()', (api_key,))
            if not cur.fetchone():
                return jsonify({'error': 'Invalid or expired API key'}), 401

    # URL格式校验
    youtube_url = request.json.get('youtube_url')
    if not re.match(r'^https?://(www\.)?(youtube\.com|youtu\.be)/', youtube_url):
        return jsonify({'error': 'Invalid YouTube URL'}), 400

    # 提交异步任务
    from tasks import process_video
    task = process_video.delay(youtube_url)
    return jsonify({
        'task_id': task.id,
        'status_url': f'/status/{task.id}'
    }), 202

@app.route('/status/<task_id>')
def get_status(task_id):
    """查询任务状态"""
    from tasks import process_video
    task = process_video.AsyncResult(task_id)
    return jsonify({
        'task_id': task.id,
        'status': task.state,
        'result': task.result if task.ready() else None
    })

if __name__ == '__main__':
    # 启动时初始化数据库并运行服务
    init_db()
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))
