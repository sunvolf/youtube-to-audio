from flask import Flask, request, jsonify, render_template, redirect, url_for
import os
import uuid
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 初始化 Flask
app = Flask(__name__)

# 加载或生成 API 秘钥
API_KEYS_FILE = "/tmp/api_keys.txt"  # Render 使用临时存储
if not os.path.exists(API_KEYS_FILE):
    with open(API_KEYS_FILE, "w") as f:
        f.write("default-key\n")  # 默认秘钥
with open(API_KEYS_FILE, "r") as f:
    API_KEYS = set(line.strip() for line in f if line.strip())

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
        if action == "generate":
            new_key = str(uuid.uuid4())
            API_KEYS.add(new_key)
            with open(API_KEYS_FILE, "a") as f:
                f.write(new_key + "\n")
            return redirect(url_for("admin"))
        elif action == "delete":
            key_to_delete = request.form.get("key")
            if key_to_delete in API_KEYS:
                API_KEYS.remove(key_to_delete)
                with open(API_KEYS_FILE, "w") as f:
                    f.writelines(key + "\n" for key in API_KEYS)
            return redirect(url_for("admin"))

    return render_template("admin.html", api_keys=API_KEYS)


# ====================
# 路由：视频转换 API
# ====================

@app.route("/convert", methods=["POST"])
def convert():
    """接收 POST 请求，提交异步任务"""
    # 验证 Authorization 头部
    auth_header = request.headers.get("Authorization")
    if not auth_header or auth_header not in API_KEYS:
        return jsonify({"error": "无效的 API 秘钥"}), 401

    data = request.json
    youtube_url = data.get("youtube_url")
    output_format = data.get("output_format", "mp3").lower()

    if not youtube_url:
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
        if task.ready():
            # 确保任务结果是 JSON 可序列化的
            result = task.result
            if isinstance(result, dict):  # 如果结果是字典，直接返回
                return jsonify(result), 200
            else:  # 如果结果不是字典，将其转换为字符串
                return jsonify({"message": str(result)}), 200
        else:
            return jsonify({"message": "任务仍在处理中"}), 202
    except Exception as e:
        # 捕获所有异常并返回可序列化的错误信息
        return jsonify({"error": str(e)}), 500


# ====================
# 启动应用
# ====================

if __name__ == "__main__":
    import os
    port = int(os.getenv("PORT", 5000))  # 使用 Render 提供的 PORT 环境变量，默认为 5000
    app.run(host="0.0.0.0", port=port, debug=False)