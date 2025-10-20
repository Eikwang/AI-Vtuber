import logging
import webbrowser
import subprocess
import sys
import os
from flask import Flask, send_from_directory, request, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import json
import queue
import threading
import time

from utils.common import Common
from utils.logger import Configure_logger

common = Common()

# 日志文件路径
log_file = "./log/log-" + common.get_bj_time(1) + ".txt"
Configure_logger(log_file)

# 获取 werkzeug 库的日志记录器
werkzeug_logger = logging.getLogger("werkzeug")
werkzeug_logger.setLevel(logging.WARNING)

config_file_path = "config.json"

app = Flask(__name__, static_folder='./')
CORS(app)  # 允许跨域请求
socketio = SocketIO(app, cors_allowed_origins="*")

# 每个字符的默认延时（毫秒）
CHARACTER_DELAY = 80
DEFAULT_START_DELAY = 2000  # 默认开始延时

class MessageQueueManager:
    def __init__(self):
        self.message_queue = queue.Queue()
        self.lock = threading.Lock()  # 用于线程同步
        self.last_message_time = None  # 上一条信息收到时间

    def enqueue_message(self, content, default_start_delay=DEFAULT_START_DELAY):
        message_length = len(content)
        current_time = int(time.time() * 1000)  # 当前时间（毫秒）

        with self.lock:
            dynamic_keep_time = message_length * CHARACTER_DELAY  # 动态计算保持时长

            if not self.message_queue.empty() and self.last_message_time is not None:
                time_diff = current_time - self.last_message_time  # 时间差
                last_content, _, last_keep_time = self.message_queue.queue[-1]  # 获取上一信息的保持时长
                
                # 计算当前信息的开始延时
                start_delay = max(0, last_keep_time - time_diff)
                start_delay = start_delay if start_delay > 0 else default_start_delay
            else:
                start_delay = default_start_delay

            # 更新最后的消息时间
            self.last_message_time = current_time

            # 将消息添加到队列中
            self.message_queue.put((content, start_delay, dynamic_keep_time))

            logging.info(f"已添加到队列：{content}，保持时长：{dynamic_keep_time}，延时：{start_delay}")

    def process_message_queue(self):
        with app.app_context():
            while True:
                message_data = self.message_queue.get()

                if message_data is None:
                    break

                content, start_delay, keep_time = message_data

                time.sleep(start_delay / 1000)

                socketio.emit('message', {
                    'content': content,
                    'start_delay': start_delay,
                    'keep_time': keep_time
                }, namespace='/')

                logging.info(f"发送内容：{content}，延时：{start_delay}毫秒，保持时长：{keep_time}")

                time.sleep(keep_time / 1000)

# 初始化消息队列管理器
message_queue_manager = MessageQueueManager()

# 启动队列处理的线程
threading.Thread(target=message_queue_manager.process_message_queue, daemon=True).start()

@app.route('/index.html')
def serve_file():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/css/index.css')
def serve_file2():
    return send_from_directory(app.static_folder, 'css/index.css')

@app.route('/js/index.js')
def serve_file3():
    return send_from_directory(app.static_folder, 'js/index.js')

@app.route('/js/socket.io.js')
def serve_file4():
    return send_from_directory(app.static_folder, 'js/socket.io.js')



@app.route('/open_desktop_window', methods=['GET', 'POST'])
def open_desktop_window():
    try:
        # 获取当前脚本所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        desktop_window_script = os.path.join(current_dir, 'desktop_caption_window.py')
        
        # 检查脚本文件是否存在
        if not os.path.exists(desktop_window_script):
            return jsonify({"code": -1, "message": "桌面窗口脚本文件不存在"})
        
        # 启动独立的桌面窗口进程
        subprocess.Popen([sys.executable, desktop_window_script], 
                        cwd=current_dir,
                        creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
        
        return jsonify({"code": 200, "message": "独立桌面窗口启动成功"})
    except Exception as e:
        return jsonify({"code": -1, "message": f"启动桌面窗口失败: {e}"})

@socketio.on('message')
def handle_message(data):
    content = data['content']
    emit('message', {'content': content}, broadcast=True)

@app.route('/get_config', methods=['GET'])
def get_config():
    try:
        # 打开文件并解析JSON数据
        with open(config_file_path, 'r', encoding="utf-8") as file:
            data = json.load(file)

        return jsonify(data)
    except Exception as e:
        return jsonify({"code": -1, "message": f"获取本地配置失败{e}"})
    
@app.route('/save_config', methods=['POST'])
def save_config():
    try:
        content = request.get_json()
        logging.info(content)

        try:
            with open(config_file_path, 'w', encoding="utf-8") as config_file:
                json.dump(content, config_file, indent=2, ensure_ascii=False)
                config_file.flush()  # 刷新缓冲区，确保写入立即生效

            # 广播配置更新到所有连接的客户端
            socketio.emit('config_update', content, broadcast=True)
            
            logging.info("配置数据已成功写入文件！")
            return jsonify({"code": 200, "message": "配置数据已成功写入文件！"})
        except Exception as e:
            logging.error(f"无法写入配置文件！{e}")
            return jsonify({"code": -1, "message": "无法写入配置文件！{e}"})
    except Exception as e:
        return jsonify({"code": -1, "message": f"无法写入配置文件！{e}"})
    
@app.route('/send_message', methods=['GET', 'POST'])
def send_message():
    try:
        if request.method == 'POST':
            data = request.get_json()
            content = data.get('content', "")
        else:  # GET 请求
            content = request.args.get('content', "")

        # 使用管理器将消息添加到队列中
        message_queue_manager.enqueue_message(content)

        return jsonify({"code": 200, "message": "数据已添加到队列"})
    except Exception as e:
        return jsonify({"code": -1, "message": f"数据发送失败\n{e}"})

if __name__ == '__main__':
    port = 5502
    # 启动桌面字幕窗口
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        desktop_window_script = os.path.join(current_dir, 'desktop_caption_window.py')
        if os.path.exists(desktop_window_script):
            subprocess.Popen([sys.executable, desktop_window_script], 
                            cwd=current_dir,
                            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0)
            logging.info("已启动桌面字幕窗口")
        else:
            logging.error("桌面窗口脚本文件不存在")
    except Exception as e:
        logging.error(f"启动桌面窗口失败: {e}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False)