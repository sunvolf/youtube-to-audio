from celery import Celery
import os
from pytube import YouTube
from moviepy.editor import AudioFileClip
import boto3
from dotenv import load_dotenv
from time import sleep

# 加载 .env 文件
load_dotenv()

# 初始化 Celery
app = Celery('tasks', broker=os.getenv("CELERY_BROKER_URL"))

# 配置结果后端
app.conf.update(
    result_backend=os.getenv("CELERY_BROKER_URL"),  # 使用相同的 Redis 实例作为结果后端
    broker_connection_retry=True,  # 显式启用重试
    broker_connection_max_retries=3,  # 最大重试次数
)

# 加载 AWS 配置
s3_client = boto3.client(
    "s3",
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)

@app.task(bind=True, max_retries=3)
def process_youtube_video(self, youtube_url, output_format="mp3"):
    try:
        # 添加延迟以减少请求频率
        sleep(2)

        # 下载视频
        yt = YouTube(youtube_url)
        video_stream = yt.streams.filter(only_audio=True).first()
        download_path = f"/tmp/{yt.video_id}.mp4"
        video_stream.download(output_path="/tmp", filename=yt.video_id + ".mp4")

        # 转换为音频
        audio_path = f"/tmp/{yt.video_id}.{output_format}"
        audio_clip = AudioFileClip(download_path)
        audio_clip.write_audiofile(audio_path)
        audio_clip.close()

        # 上传到 S3
        s3_bucket_name = os.getenv("S3_BUCKET_NAME")
        object_name = os.path.basename(audio_path)
        s3_client.upload_file(audio_path, s3_bucket_name, object_name, ExtraArgs={"ACL": "public-read"})
        file_url = f"https://{s3_bucket_name}.s3.amazonaws.com/{object_name}"

        # 删除临时文件
        if os.path.exists(download_path):
            os.remove(download_path)  # 删除下载的视频文件
        if os.path.exists(audio_path):
            os.remove(audio_path)  # 删除生成的音频文件

        return {"message": "转换成功", "file_url": file_url}
    except Exception as e:
        # 捕获 HTTP 429 错误并重试
        if "HTTP Error 429" in str(e):
            self.retry(countdown=5)  # 5 秒后重试
        # 返回可序列化的错误信息
        return {"error": str(e)}