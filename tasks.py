"""
异步任务处理模块
整合Celery高性能配置与视频处理逻辑
"""

from celery import Celery
import os
import subprocess
import tempfile
from pytube import YouTube

# 初始化Celery应用（使用Redis作为消息代理和结果后端）
app = Celery(
    'tasks',
    broker=os.getenv('REDIS_URL'),
    backend=os.getenv('REDIS_URL')
)

# 高性能配置参数
app.conf.update(
    task_track_started=True,        # 启用任务状态跟踪
    result_extended=True,           # 保留详细任务结果
    worker_max_tasks_per_child=10,  # 每个工作进程处理10个任务后重启（防止内存泄漏）
    task_acks_late=True,            # 确保任务不会在崩溃时丢失
    worker_prefetch_multiplier=1,   # 公平任务分配模式
    worker_concurrency=2            # 并行工作进程数（根据内存调整）
)

@app.task(bind=True, max_retries=3)
def process_video(self, youtube_url):
    """
    视频处理任务主逻辑
    输入：YouTube视频URL
    输出：MP3文件URL或错误信息
    """
    try:
        yt = YouTube(youtube_url)
        video_id = yt.video_id
        
        # 使用临时目录处理文件（自动清理）
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
            return {'url': f'https://cdn.example.com/{video_id}.mp3'}

    except subprocess.TimeoutExpired:
        self.retry(countdown=60, exc=Exception('FFmpeg转换超时'))
    except Exception as e:
        self.retry(countdown=30, exc=e)  # 30秒后重试
        return {'error': str(e)}
