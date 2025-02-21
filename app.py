import os
import uuid
import re
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_httpauth import HTTPBasicAuth
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='static', static_url_path='/static')
auth = HTTPBasicAuth()

# PostgreSQL 连接
def get_db():
    return psycopg2.connect(
        dbname=os.getenv('PGDATABASE'),
        user=os.getenv('PGUSER'),
        password=os.getenv('PGPASSWORD'),
        host=os.getenv('PGHOST'),
        port=os.getenv('PGPORT'),
        sslmode='require'
    )

# 初始化数据库表
def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS api_keys (
                    id SERIAL PRIMARY KEY,
                    key VARCHAR(36) UNIQUE NOT NULL,
                    expiry_time TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS conversions (
                    id SERIAL PRIMARY KEY,
                    task_id VARCHAR(255) UNIQUE NOT NULL,
                    youtube_id VARCHAR(255) NOT NULL,
                    status VARCHAR(50) DEFAULT 'pending',
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                )
            ''')
        conn.commit()

# 身份验证
ADMIN_USER = os.getenv('ADMIN_USER')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')

@auth.verify_password
def verify_password(username, password):
    return username == ADMIN_USER and password == ADMIN_PASSWORD

@app.route('/')
def index():
    return "YouTube音频转换服务 - 访问 /admin 管理API密钥"

@app.route('/admin', methods=['GET', 'POST'])
@auth.login_required
def admin():
    if request.method == 'POST':
        action = request.form.get('action')
        with get_db() as conn:
            if action == 'generate':
                new_key = str(uuid.uuid4())
                expiry = datetime.now() + timedelta(days=180)
                with conn.cursor() as cur:
                    cur.execute(
                        'INSERT INTO api_keys (key, expiry_time) VALUES (%s, %s)',
                        (new_key, expiry)
                    )
                conn.commit()
            elif action == 'delete':
                key = request.form.get('key')
                with conn.cursor() as cur:
                    cur.execute('DELETE FROM api_keys WHERE key = %s', (key,))
                conn.commit()
        return redirect(url_for('admin'))
    
    with get_db() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT key, expiry_time FROM api_keys WHERE expiry_time > NOW()')
            keys = cur.fetchall()
    return render_template('admin.html', api_keys=keys)

@app.route('/convert', methods=['POST'])
def convert():
    api_key = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
    if not api_key:
        return jsonify({'error': '缺少授权头'}), 401
    
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT 1 FROM api_keys WHERE key = %s AND expiry_time > NOW()', (api_key,))
            if not cur.fetchone():
                return jsonify({'error': '无效或过期的API密钥'}), 401

    data = request.json
    youtube_url = data.get('youtube_url')
    if not youtube_url or not re.match(r'^(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+', youtube_url):
        return jsonify({'error': '无效的YouTube URL'}), 400
    
    output_format = data.get('output_format', 'mp3').lower()
    if output_format not in ['mp3', 'm4a']:
        return jsonify({'error': '仅支持 mp3/m4a 格式'}), 400

    from tasks import process_youtube_video
    task = process_youtube_video.delay(youtube_url, output_format)
    return jsonify({
        'task_id': task.id,
        'status_url': f'/status/{task.id}'
    }), 202

@app.route('/status/<task_id>')
def get_status(task_id):
    from tasks import process_youtube_video
    task = process_youtube_video.AsyncResult(task_id)
    return jsonify({
        'task_id': task.id,
        'status': task.state,
        'result': task.result if task.ready() else None,
        'progress': task.info.get('progress') if task.info else None
    })

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))
