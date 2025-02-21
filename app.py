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

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 初始化Flask应用
app = Flask(__name__, static_folder='static', static_url_path='/static')
auth = HTTPBasicAuth()

# 导入数据库初始化函数
from init_db import init_db

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
            with tempfile.TemporaryDirectory() as tmpdir:
                # 下载最佳音质音频流
                stream = yt.streams.filter(only_audio=True).order_by('abr').last()
                download_path = stream.download(output_path=tmpdir)
                
                # FFmpeg转换参数
                output_path = os.path.join(tmpdir, f'{video_id}.mp3')
                subprocess.run([
                    'ffmpeg',
                    '-i', download_path,    # 输入文件
                    '-vn',                  # 禁用视频流
                    '-ar', '44100',         # 采样率44.1kHz（CD标准）
                    '-ac', '2',             # 立体声
                    '-b:a', '192k',         # 音频比特率
                    '-y',                   # 覆盖输出文件（防止报错）
                    output_path
                ], check=True, timeout=300)  # 设置5分钟超时
                
                # 示例返回（需替换为实际云存储地址）
                mp3_url = upload_to_s3(output_path, video_id)
                return {'url': mp3_url}
        except subprocess.TimeoutExpired:
            self.retry(countdown=60, exc=Exception('FFmpeg转换超时'))
        except Exception as e:
            self.retry(countdown=30, exc=e)  # 30秒后重试
            return {'error': str(e)}

if __name__ == '__main__':
    # 启动时初始化数据库并运行服务
    init_db()
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000))