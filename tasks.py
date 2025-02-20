from celery import Celery, states
import os
from pytube import YouTube
from moviepy.editor import AudioFileClip
import boto3
from dotenv import load_dotenv
from time import sleep
import random
import traceback
import redis

# 加载 .env 文件
load_dotenv()

# 初始化 Celery
app = Celery('tasks', broker=os.getenv("CELERY_BROKER_URL"))

# 配置结果后端
app.conf.update(
    result_backend=os.getenv("CELERY_BROKER_URL"),  # 使用相同的 Redis 实例作为结果后端
    broker_connection_retry=True,  # 显式启用重试
    broker_connection_max_retries=3,  # 最大重试次数
    task_time_limit=600,  # 单个任务的最大运行时间为 600 秒（10 分钟）
    task_soft_time_limit=300,  # 软性超时时间为 300 秒（5 分钟）
)

# 初始化 Redis 客户端
redis_client = redis.Redis.from_url(os.getenv("CELERY_BROKER_URL"))

# 加载 AWS 配置
s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)

@app.task(bind=True, max_retries=5)
def process_youtube_video(self, youtube_url, output_format="mp3"):
    try:
        # 检查 Redis 缓存中是否已有该视频
        yt = YouTube(youtube_url)
        video_id = yt.video_id
        cached_file = redis_client.get(video_id)
        if cached_file:
            file_url = cached_file.decode("utf-8")
            return {"message": "转换成功", "file_url": file_url}

        # 设置随机 User-Agent
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        ]
        yt._user_agent = random.choice(user_agents)

        # 动态延迟 1-8 秒
        sleep(random.uniform(1, 8))

        # 更新任务状态：开始下载视频
        self.update_state(state="PROGRESS", meta={"status": "正在下载视频..."})

        # 下载视频
        video_stream = yt.streams.filter(only_audio=True).first()
        download_path = f"/tmp/{yt.video_id}.mp4"
        video_stream.download(output_path="/tmp", filename=yt.video_id + ".mp4", timeout=30)  # 设置超时时间

        # 更新任务状态：开始转换音频
        self.update_state(state="PROGRESS", meta={"status": "正在转换音频..."})

        # 转换为音频
        audio_path = f"/tmp/{yt.video_id}.{output_format}"
        audio_clip = AudioFileClip(download_path)
        audio_clip.write_audiofile(audio_path)
        audio_clip.close()

        # 更新任务状态：开始上传到 S3
        self.update_state(state="PROGRESS", meta={"status": "正在上传到 S3..."})

        # 上传到 S3
        s3_bucket_name = os.getenv("S3_BUCKET_NAME")
        object_name = os.path.basename(audio_path)
        s3_client.upload_file(
            audio_path,
            s3_bucket_name,
            object_name,
            ExtraArgs={"ACL": "public-read"},
            Config=boto3.s3.transfer.TransferConfig(use_threads=False),
            Callback=None,
            timeout=30  # 设置超时时间
        )
        file_url = f"https://{s3_bucket_name}.s3.amazonaws.com/{object_name}"

        # 将文件 URL 缓存到 Redis
        redis_client.set(video_id, file_url, ex=86400)  # 缓存 1 天

        # 删除临时文件
        if os.path.exists(download_path):
            os.remove(download_path)  # 删除下载的视频文件
        if os.path.exists(audio_path):
            os.remove(audio_path)  # 删除生成的音频文件

        # 更新任务状态：完成
        self.update_state(state="SUCCESS", meta={"status": "任务完成", "file_url": file_url})
        return {"message": "转换成功", "file_url": file_url}
    except Exception as e:
        # 捕获 HTTP 403 错误并重试
        if "HTTP Error 403" in str(e):
            countdown = 2 ** self.request.retries  # 指数退避算法
            self.retry(countdown=countdown)
        # 返回可序列化的错误信息
        error_message = f"Error processing task: {str(e)}"
        print(error_message)
        traceback.print_exc()
        return {"error": error_message}