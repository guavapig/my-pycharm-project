from flask import Flask, request, abort, jsonify
import json
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, VideoSendMessage, ImageSendMessage
import subprocess
import os
import requests
import boto3
from botocore.exceptions import NoCredentialsError
import mysql.connector
import re
from linebot.models import TemplateSendMessage, ButtonsTemplate, URIAction

app = Flask(__name__)

# 设置你的 LINE BOT channel access token 和 channel secret
line_bot_api = LineBotApi('EmdGNSMZYxoNTNxWWr157OG4s1YCiDbFgj4YHLhL8s46a0W9Ehsfrtw8Un2sewXgK/QYRP0zTmrpjCKYaHLMd4Rr1Z2yvFhJXpvH5OpFXglZknRvZwe/JLvDcFOCHfAo1ES1v1TUvzKGgwllqrNRVAdB04t89/1O/w1cDnyilFU=')
handler = WebhookHandler('c619d13f431d5f064209a5d0def310ea')


# 從環境變數中讀取 AWS S3 配置信息
S3_BUCKET = os.getenv('S3_BUCKET')
S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY')
S3_SECRET_KEY = os.getenv('S3_SECRET_KEY')
S3_REGION = os.getenv('S3_REGION')

# 確保讀取到的環境變數不是 None
if not all([S3_BUCKET, S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION]):
    raise EnvironmentError("AWS S3 配置的環境變數未正確設置")

# 创建 S3 客户端
s3_client = boto3.client(
    's3',
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION
)

# 用户状态字典
user_state = {}

selection = '2'  # 默认选择原视频长度

@app.route("/callback", methods=['POST'])
def callback():
    # 获取HTTP请求body
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info(f"Request body: {body}")

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)
    except Exception as e:
        app.logger.error(f"Error: {e}")
        abort(500)

    return 'OK'

@app.route("/receive_video_and_image", methods=['POST'])
def receive_video_and_image():
    user_id = request.form.get('user_id')
    video_url = request.form.get('video_url')
    image_file = request.files.get('image')

    if not user_id or not video_url or not image_file:
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    # 保存图片文件
    image_path = f"./{image_file.filename}"
    image_file.save(image_path)

    # 将图片上传至 S3
    image_url = upload_to_s3(image_path)
    if not image_url:
        return jsonify({"status": "error", "message": "Failed to upload image"}), 500
    # 处理视频URL和图片URL
    handle_video_selection(video_url, image_url, user_id, selection)


    return jsonify({"status": "success"}), 200


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    global selection
    user_id = event.source.user_id
    user_message = event.message.text
    app.logger.info(f"Received message from {user_id}: {user_message}")

    if user_message == '通知模式':
        if selection == '1':
            send_text(event.reply_token,'目前偵測結果為影片形式!')
            selection = '2'
        else:
            send_text(event.reply_token, '目前偵測結果為圖片形式!')
            selection = '1'
    elif user_message == '聯繫我們':
        send_emergency_contact(user_id)
    elif user_message == '事件回饋':
        user_state[user_id] = 'feedback1'
        send_text(event.reply_token, '請輸入欲回饋事件之ID')
    elif re.fullmatch(r'\d{1,4}', user_message) and user_state.get(user_id) == 'feedback1':
        send_text(event.reply_token, f'事件ID: {user_message}\n請以數字1,2,3,4記錄此次事件嚴重程度，數字1為最輕微，數字4為最嚴重')
        user_state[user_id] = 'feedback2'
    elif user_message in ['1', '2', '3', '4'] and user_state.get(user_id) == 'feedback2':
        send_text(event.reply_token, '回饋完成!')
        user_state[user_id] = None
    else:
        user_state[user_id] = None

def send_text(reply_token, text):
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=text)
    )

def send_image(user_id, image_url):
    line_bot_api.push_message(
        user_id,
        ImageSendMessage(
            original_content_url=image_url,
            preview_image_url=image_url
        )
    )

def send_video(user_id, video_url):
    # 使用 LINE Messaging API 发送视频
    line_bot_api.push_message(
        user_id,
        VideoSendMessage(
            original_content_url=video_url,
            preview_image_url='https://via.placeholder.com/1x1.png?text='  # 使用透明的1x1像素图像
        )
    )
# 使用 push_message 而不是 reply_message
def send_text_to_user(user_id, text):
    line_bot_api.push_message(
        user_id,
        TextSendMessage(text=text)
    )

def handle_video_selection(video_url, image_url, user_id, selection):
    # 發送圖片或影片
    if selection == '1':
        send_image(user_id, image_url)
    elif selection == '2':
        send_video(user_id, video_url)
    else:
        app.logger.error(f"Invalid selection: {selection}")
        return

def send_emergency_contact(user_id):
    line_bot_api.push_message(
        user_id,
        TemplateSendMessage(
            alt_text='聯絡我們',
            template=ButtonsTemplate(
                title='聯繫我們',
                text='點擊按鈕來打電話',
                actions=[
                    URIAction(
                        label='撥打電話',
                        uri='tel:0912418370'  # 这里可以换成你想要的紧急联系电话
                    )
                ]
            )
        )
    )

def upload_to_s3(file_path):
    s3_file_name = os.path.basename(file_path)
    try:
        s3_client.upload_file(file_path, S3_BUCKET, s3_file_name)
        s3_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{s3_file_name}"
        return s3_url
    except NoCredentialsError:
        print("AWS credentials not available")
        return None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
