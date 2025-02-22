"""
异步任务处理模块
整合Celery高性能配置与视频处理逻辑
"""
from celery import Celery
import os
import subprocess
import tempfile
from pytube import YouTube
import boto3
import logging

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
    worker_concurrency=int(os.getenv('CELERY_CONCURRENCY', 2))  # 并行工作进程数（根据内存调整）
)

def upload_to_s3(file_path, video_id):
    """将文件上传到AWS S3"""
    s3 = boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )
    bucket_name = os.getenv('S3_BUCKET_NAME')
    s3.upload_file(file_path, bucket_name, f'{video_id}.mp3')
    return f'https://{bucket_name}.s3.amazonaws.com/{video_id}.mp3'

@app.task(bind=True, max_retries=3)
def process_video(self, youtube_url):
    """
    视频处理任务主逻辑
    输入：YouTube视频URL
    输出：MP3文件URL或错误信息
    """
    try:
        logging.info(f"Processing video: {youtube_url}")
        yt = YouTube(youtube_url)
        video_id = yt.video_id
        
        # 使用临时目录处理文件（自动清理）
        with tempfile.TemporaryDirectory() as tmpdir:
            # 下载最佳音质音频流
            stream = yt.streams.filter(only_audio=True).order_by('abr').last()
            download_path = stream.download(output_path=tmpdir)
            
            # FFmpeg转换参数
            output_path = os.path.join(tmpdir, f'{video_id}.mp3')
            try:
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
            except subprocess.TimeoutExpired:
                logging.warning("FFmpeg转换超时，重试中...")
                self.retry(countdown=min(60 * 2 ** self.request.retries, 3600), exc=Exception('FFmpeg转换超时'))
                return {'error': 'FFmpeg conversion timed out'}
            
            # 上传到S3并返回URL
            mp3_url = upload_to_s3(output_path, video_id)
            return {'url': mp3_url}
    except Exception as e:
        logging.error(f"Error processing video: {e}")
        self.retry(countdown=min(30 * 2 ** self.request.retries, 3600), exc=e)
        return {'error': str(e)}