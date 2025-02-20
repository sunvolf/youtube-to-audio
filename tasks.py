from celery import Celery
import os
import subprocess
import tempfile
from pytube import YouTube
import boto3
from botocore.exceptions import ClientError
import redis
from dotenv import load_dotenv
from time import sleep
import random

load_dotenv()

app = Celery(
    'tasks',
    broker=os.getenv('REDIS_URL'),
    backend=os.getenv('REDIS_URL')
)

app.conf.update(
    task_serializer='json',
    result_serializer='json',
    task_time_limit=600,
    broker_connection_retry_on_startup=True
)

# AWS 配置
s3 = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

# Redis 连接
redis_client = redis.Redis.from_url(os.getenv('REDIS_URL'))

def generate_presigned_url(bucket, key):
    try:
        return s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=3600
        )
    except ClientError as e:
        app.log.error(f'S3预签名URL生成失败: {e}')
        return None

@app.task(bind=True, max_retries=3)
def process_youtube_video(self, youtube_url, output_format):
    try:
        yt = YouTube(youtube_url)
        video_id = yt.video_id
        
        # 检查缓存
        if cached_url := redis_client.get(video_id):
            return {'file_url': cached_url.decode(), 'cached': True}
        
        # 随机化请求特征
        yt._user_agent = random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36...'
        ])
        sleep(random.uniform(1, 5))
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # 下载音频
            self.update_state(state='PROGRESS', meta={'status': '下载中...'})
            stream = yt.streams.filter(only_audio=True).first()
            mp4_path = f'{tmpdir}/{video_id}.mp4'
            stream.download(output_path=tmpdir, filename=f'{video_id}.mp4')
            
            # 转换格式
            self.update_state(state='PROGRESS', meta={'status': '转换中...'})
            audio_path = f'{tmpdir}/{video_id}.{output_format}'
            codec = 'libmp3lame' if output_format == 'mp3' else 'aac'
            subprocess.run([
                'ffmpeg', '-y', '-i', mp4_path,
                '-vn', '-ar', '44100', '-ac', '2',
                '-codec:a', codec, '-b:a', '192k', audio_path
            ], check=True)
            
            # 上传到S3
            self.update_state(state='PROGRESS', meta={'status': '上传中...'})
            bucket = os.getenv('S3_BUCKET')
            s3.upload_file(audio_path, bucket, f'{video_id}.{output_format}')
            file_url = generate_presigned_url(bucket, f'{video_id}.{output_format}')
            
            # 更新缓存
            redis_client.setex(video_id, 86400, file_url)
            return {'file_url': file_url}
            
    except Exception as e:
        if 'HTTP Error 403' in str(e):
            self.retry(countdown=2 ** self.request.retries)
        return {'error': str(e)}
