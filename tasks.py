from celery import Celery
import os
import subprocess
import tempfile
from pytube import YouTube
import boto3
from botocore.exceptions import ClientError
import redis
import psycopg2
from dotenv import load_dotenv
import random
from time import sleep

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

s3 = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
)

redis_client = redis.Redis.from_url(os.getenv('REDIS_URL'))

def update_task_status(task_id, status):
    try:
        with psycopg2.connect(
            dbname=os.getenv('PGDATABASE'),
            user=os.getenv('PGUSER'),
            password=os.getenv('PGPASSWORD'),
            host=os.getenv('PGHOST'),
            port=os.getenv('PGPORT'),
            sslmode='require'
        ) as conn:
            with conn.cursor() as cur:
                cur.execute('''
                    INSERT INTO conversions (task_id, status)
                    VALUES (%s, %s)
                    ON CONFLICT (task_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        completed_at = CASE WHEN EXCLUDED.status = 'SUCCESS' THEN NOW() ELSE NULL END
                ''', (task_id, status))
                conn.commit()
    except Exception as e:
        app.log.error(f'Database update failed: {str(e)}')

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
        
        if cached_url := redis_client.get(video_id):
            return {'file_url': cached_url.decode(), 'cached': True}
        
        yt._user_agent = random.choice([
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ])
        sleep(random.uniform(1, 3))

        with tempfile.TemporaryDirectory() as tmpdir:
            self.update_state(state='PROGRESS', meta={'progress': 30, 'status': '下载中...'})
            update_task_status(self.request.id, 'DOWNLOADING')
            
            stream = yt.streams.filter(only_audio=True).order_by('abr').last()
            mp4_path = os.path.join(tmpdir, f'{video_id}.mp4')
            stream.download(output_path=tmpdir, filename=os.path.basename(mp4_path), timeout=30)

            self.update_state(state='PROGRESS', meta={'progress': 60, 'status': '转换中...'})
            update_task_status(self.request.id, 'CONVERTING')
            
            audio_path = os.path.join(tmpdir, f'{video_id}.{output_format}')
            codec = 'libmp3lame' if output_format == 'mp3' else 'aac'
            subprocess.run([
                'ffmpeg', '-y', '-i', mp4_path,
                '-vn', '-ar', '44100', '-ac', '2',
                '-codec:a', codec, '-b:a', '192k', audio_path
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            self.update_state(state='PROGRESS', meta={'progress': 90, 'status': '上传中...'})
            update_task_status(self.request.id, 'UPLOADING')
            
            bucket = os.getenv('S3_BUCKET')
            s3_key = f'audio/{video_id}.{output_format}'
            s3.upload_file(audio_path, bucket, s3_key)
            presigned_url = generate_presigned_url(bucket, s3_key)

            redis_client.setex(video_id, 86400, presigned_url)
            update_task_status(self.request.id, 'SUCCESS')
            return {'file_url': presigned_url}

    except Exception as e:
        update_task_status(self.request.id, 'FAILED')
        if 'HTTP Error 403' in str(e):
            self.retry(countdown=2 ** self.request.retries)
        return {'error': str(e)}
