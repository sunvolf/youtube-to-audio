from flask import Flask, request, jsonify, render_template, redirect, url_for
import os
import uuid
from dotenv import load_dotenv
from datetime import datetime, timedelta

# 加载 .env 文件
load_dotenv()

# 初始化 Flask
app = Flask(__name__)

# 定义 API 秘钥文件路径
API_KEYS_FILE = "/tmp/api_keys.txt"  # Render 使用临时存储

# 加载或生成 API 秘钥
def load_api_keys():
    if not os.path.exists(API_KEYS_FILE):
        with open(API_KEYS_FILE, "w") as f:
            f.write("default-key\n")  # 默认秘钥
    api_keys = []
    try:
        with open(API_KEYS_FILE, "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) == 2:  # 格式：key|expiry_time
                    key, expiry_time_str = parts
                    try:
                        expiry_time = datetime.strptime(expiry_time_str, "%Y-%m-%d %H:%M:%S")
                        if expiry_time > datetime.now():
                            api_keys.append((key, expiry_time))
                    except ValueError:
                        # 如果日期格式解析失败，跳过该行
                        continue
    except Exception as e:
        print(f"Error loading API keys: {str(e)}")
    return set(api_keys)

def save_api_keys(api_keys):
    try:
        with open(API_KEYS_FILE, "w") as f:
            for key, expiry_time in api_keys:
                f.write(f"{key}|{expiry_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    except Exception as e:
        print(f"Error saving API keys: {str(e)}")

# ====================
# 路由：主页（默认根路径）
# ====================
@app.route("/")
def index():
    return "Welcome to the YouTube to Audio Converter!"

# ====================
# 路由：API 秘钥管理
# ====================

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        action = request.form.get("action")
        api_keys = load_api_keys()
        if action == "generate":
            new_key = str(uuid.uuid4())
            expiry_time = datetime.now() + timedelta(days=180)  # 设置有效期为 180 天
            api_keys.add((new_key, expiry_time))
            save_api_keys(api_keys)
            return redirect(url_for("admin"))
        elif action == "delete":
            key_to_delete = request.form.get("key")
            api_keys = {(key, expiry_time) for key, expiry_time in api_keys if key != key_to_delete}
            save_api_keys(api_keys)
            return redirect(url_for("admin"))

    # 过滤掉默认秘钥
    api_keys = load_api_keys()
    filtered_keys = [(key, expiry_time) for key, expiry_time in api_keys if key != "default-key"]
    return render_template("admin.html", api_keys=filtered_keys)


# ====================
# 路由：视频转换 API
# ====================

@app.route("/convert", methods=["POST"])
def convert():
    """接收 POST 请求，提交异步任务"""
    # 验证 Authorization 头部
    auth_header = request.headers.get("Authorization")
    api_keys = load_api_keys()
    valid_keys = {key for key, _ in api_keys}
    if not auth_header or auth_header not in valid_keys:
        return jsonify({"error": "无效的 API 秘钥"}), 401

    data = request.json
    youtube_url = data.get("youtube_url")
    output_format = data.get("output_format", "mp3").lower()

    if not youtube_url or "youtube.com/watch" not in youtube_url:
        return jsonify({"error": "请输入有效的 YouTube 视频链接"}), 400

    if output_format not in ["mp3", "m4a"]:
        return jsonify({"error": "无效的输出格式，请选择 mp3 或 m4a"}), 400

    # 提交异步任务
    from tasks import process_youtube_video
    task = process_youtube_video.delay(youtube_url, output_format)
    return jsonify({"message": "任务已提交", "task_id": task.id}), 202


@app.route("/status/<task_id>", methods=["GET"])
def task_status(task_id):
    """查询任务状态"""
    from tasks import process_youtube_video
    try:
        task = process_youtube_video.AsyncResult(task_id)
        if task.state == "PENDING":
            return jsonify({"message": "任务仍在处理中"}), 202
        elif task.state == "PROGRESS":
            return jsonify({"message": task.info.get("status")}), 202
        elif task.state == "SUCCESS":
            return jsonify(task.info), 200
        elif task.state == "FAILURE":
            # 返回具体的错误信息
            return jsonify({"error": task.result.get("error", "未知错误")}), 500
        else:
            return jsonify({"error": "任务状态未知"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ====================
# 启动应用
# ====================

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 5000))  # 使用 Render 提供的 PORT 环境变量，默认为 5000
    app.run(host="0.0.0.0", port=port, debug=False)