#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立桌面字幕显示窗口
支持置顶、拖拽、透明度调节等功能
通过WebSocket与Flask后端通信
"""

import tkinter as tk
from tkinter import ttk, messagebox
import json
import threading
import time
import requests
import socketio
import logging
from typing import Dict, Any

class DesktopCaptionWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.config = {}
        self.socket_client = None
        self.is_connected = False
        self.current_message = ""
        self.message_queue = []
        self.is_processing = False
        
        # 窗口拖拽相关变量
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.is_dragging = False
        
        self.setup_window()
        self.setup_ui()
        self.setup_socket()
        self.load_config()
        
    def setup_window(self):
        """设置窗口基本属性"""
        self.root.title("字幕显示窗口")
        self.root.geometry("600x200+100+100")
        
        # 设置窗口置顶
        self.root.attributes('-topmost', True)
        
        # 设置窗口透明度
        self.root.attributes('-alpha', 0.9)
        
        # 保留正常窗口边框和标题栏，以便在任务栏显示和被直播工具捕捉
        # self.root.overrideredirect(True)  # 注释掉此行
        
        # 设置窗口背景色
        self.root.configure(bg='#219175')
        
        # 由于保留了标题栏，主要通过标题栏拖拽，但也可以通过字幕区域拖拽
        # 拖拽功能将在setup_ui中绑定到字幕标签
        
        # 绑定右键菜单
        self.root.bind('<Button-3>', self.show_context_menu)
        
        # 绑定键盘事件
        self.root.bind('<Escape>', lambda e: self.toggle_controls())
        self.root.bind('<F1>', lambda e: self.show_help())
        
    def setup_ui(self):
        """设置用户界面"""
        # 主容器
        self.main_frame = tk.Frame(self.root, bg='#219175')
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 字幕显示标签
        self.caption_label = tk.Label(
            self.main_frame,
            text="字幕显示区域\n按ESC显示控制面板，按F1查看帮助",
            font=("黑体", 24),
            fg="#000000",
            bg="#ffffff",
            wraplength=580,
            justify=tk.CENTER,
            relief=tk.FLAT,
            bd=0
        )
        self.caption_label.pack(fill=tk.BOTH, expand=True)
        
        # 绑定标签的拖拽事件
        self.caption_label.bind('<Button-1>', self.start_drag)
        self.caption_label.bind('<B1-Motion>', self.on_drag)
        self.caption_label.bind('<ButtonRelease-1>', self.stop_drag)
        self.caption_label.bind('<Button-3>', self.show_context_menu)
        
        # 为字幕标签绑定拖拽事件，方便用户拖拽窗口
        self.caption_label.bind('<Button-1>', self.start_drag)
        self.caption_label.bind('<B1-Motion>', self.on_drag)
        self.caption_label.bind('<ButtonRelease-1>', self.stop_drag)
        
        # 控制面板（默认隐藏）
        self.control_frame = tk.Frame(self.root, bg='#333333', relief=tk.RAISED, bd=2)
        self.setup_control_panel()
        
    def setup_control_panel(self):
        """设置控制面板"""
        # 标题
        title_label = tk.Label(
            self.control_frame,
            text="字幕窗口控制面板",
            font=("微软雅黑", 12, "bold"),
            fg="white",
            bg="#333333"
        )
        title_label.pack(pady=5)
        
        # 透明度控制
        alpha_frame = tk.Frame(self.control_frame, bg="#333333")
        alpha_frame.pack(fill=tk.X, padx=10, pady=2)
        
        tk.Label(alpha_frame, text="透明度:", fg="white", bg="#333333").pack(side=tk.LEFT)
        self.alpha_var = tk.DoubleVar(value=0.9)
        alpha_scale = tk.Scale(
            alpha_frame,
            from_=0.3,
            to=1.0,
            resolution=0.1,
            orient=tk.HORIZONTAL,
            variable=self.alpha_var,
            command=self.update_alpha,
            bg="#333333",
            fg="white",
            highlightthickness=0
        )
        alpha_scale.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        
        # 置顶控制
        topmost_frame = tk.Frame(self.control_frame, bg="#333333")
        topmost_frame.pack(fill=tk.X, padx=10, pady=2)
        
        self.topmost_var = tk.BooleanVar(value=True)
        topmost_check = tk.Checkbutton(
            topmost_frame,
            text="窗口置顶",
            variable=self.topmost_var,
            command=self.toggle_topmost,
            fg="white",
            bg="#333333",
            selectcolor="#555555"
        )
        topmost_check.pack(side=tk.LEFT)
        
        # 连接状态
        status_frame = tk.Frame(self.control_frame, bg="#333333")
        status_frame.pack(fill=tk.X, padx=10, pady=2)
        
        tk.Label(status_frame, text="连接状态:", fg="white", bg="#333333").pack(side=tk.LEFT)
        self.status_label = tk.Label(
            status_frame,
            text="未连接",
            fg="red",
            bg="#333333"
        )
        self.status_label.pack(side=tk.LEFT, padx=(5, 0))
        
        # 按钮区域
        button_frame = tk.Frame(self.control_frame, bg="#333333")
        button_frame.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Button(
            button_frame,
            text="重新连接",
            command=self.reconnect,
            bg="#555555",
            fg="white",
            relief=tk.FLAT
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Button(
            button_frame,
            text="刷新配置",
            command=self.load_config,
            bg="#555555",
            fg="white",
            relief=tk.FLAT
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Button(
            button_frame,
            text="关闭窗口",
            command=self.close_window,
            bg="#cc4444",
            fg="white",
            relief=tk.FLAT
        ).pack(side=tk.RIGHT, padx=2)
        
        tk.Button(
            button_frame,
            text="隐藏面板",
            command=self.hide_controls,
            bg="#555555",
            fg="white",
            relief=tk.FLAT
        ).pack(side=tk.RIGHT, padx=2)
        
    def setup_socket(self):
        """设置Socket连接"""
        self.socket_client = socketio.Client()
        
        @self.socket_client.event
        def connect():
            self.is_connected = True
            self.update_status("已连接", "green")
            logging.info("Socket连接成功")
            
        @self.socket_client.event
        def disconnect():
            self.is_connected = False
            self.update_status("连接断开", "red")
            logging.info("Socket连接断开")
            
        @self.socket_client.event
        def message(data):
            content = data.get('content', '')
            if content:
                self.add_message_to_queue(content)
                
        @self.socket_client.event
        def config_update(data):
            self.config = data
            self.apply_config()
            
    def connect_to_server(self):
        """连接到服务器"""
        try:
            self.socket_client.connect('http://localhost:5502')
        except Exception as e:
            self.update_status(f"连接失败: {str(e)}", "red")
            logging.error(f"Socket连接失败: {e}")
            
    def load_config(self):
        """从服务器加载配置"""
        try:
            response = requests.get('http://localhost:5502/get_config', timeout=5)
            if response.status_code == 200:
                self.config = response.json()
                self.apply_config()
                logging.info("配置加载成功")
            else:
                logging.error(f"配置加载失败: {response.status_code}")
        except Exception as e:
            logging.error(f"配置加载异常: {e}")
            # 使用默认配置
            self.use_default_config()
            
    def use_default_config(self):
        """使用默认配置"""
        self.config = {
            "bg_color": "#ffffff",
            "body_bg_color": "#219175",
            "font_color": "#000000",
            "subtitle_bg_height": "200px",
            "subtitle_bg_width": "600px",
            "subtitle_font_family": "黑体",
            "subtitle_font_size": "24px",
            "subtitle_font_weight": "400"
        }
        self.apply_config()
        
    def apply_config(self):
        """应用配置到窗口"""
        try:
            # 更新窗口背景色
            bg_color = self.config.get('body_bg_color', '#219175')
            self.root.configure(bg=bg_color)
            self.main_frame.configure(bg=bg_color)
            
            # 更新字幕样式
            font_family = self.config.get('subtitle_font_family', '黑体')
            font_size = int(self.config.get('subtitle_font_size', '24px').replace('px', ''))
            font_color = self.config.get('font_color', '#000000')
            bg_color = self.config.get('bg_color', '#ffffff')
            
            self.caption_label.configure(
                font=(font_family, font_size),
                fg=font_color,
                bg=bg_color
            )
            
            # 更新窗口尺寸
            width = int(self.config.get('subtitle_bg_width', '600px').replace('px', ''))
            height = int(self.config.get('subtitle_bg_height', '200px').replace('px', ''))
            
            # 获取当前窗口位置
            current_geometry = self.root.geometry()
            if '+' in current_geometry:
                size_part, pos_part = current_geometry.split('+', 1)
                x, y = pos_part.split('+') if '+' in pos_part else pos_part.split('-', 1)
                new_geometry = f"{width}x{height}+{x}+{y}"
            else:
                new_geometry = f"{width}x{height}+100+100"
                
            self.root.geometry(new_geometry)
            
        except Exception as e:
            logging.error(f"应用配置失败: {e}")
            
    def add_message_to_queue(self, message):
        """添加消息到队列"""
        self.message_queue.append(message)
        if not self.is_processing:
            self.process_message_queue()
            
    def process_message_queue(self):
        """处理消息队列"""
        if not self.message_queue:
            self.is_processing = False
            return
            
        self.is_processing = True
        message = self.message_queue.pop(0)
        
        # 在主线程中更新UI
        self.root.after(0, lambda: self.display_message(message))
        
        # 设置消息显示时间
        show_time = len(message) * 80 + 2000  # 根据消息长度计算显示时间
        
        # 延时后处理下一条消息
        threading.Timer(show_time / 1000.0, self.process_message_queue).start()
        
    def display_message(self, message):
        """显示消息"""
        self.current_message = message
        self.caption_label.configure(text=message)
        
    def start_drag(self, event):
        """开始拖拽"""
        self.is_dragging = True
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root
        
    def on_drag(self, event):
        """拖拽中"""
        if self.is_dragging:
            x = self.root.winfo_x() + (event.x_root - self.drag_start_x)
            y = self.root.winfo_y() + (event.y_root - self.drag_start_y)
            self.root.geometry(f"+{x}+{y}")
            self.drag_start_x = event.x_root
            self.drag_start_y = event.y_root
            
    def stop_drag(self, event):
        """停止拖拽"""
        self.is_dragging = False
        
    def show_context_menu(self, event):
        """显示右键菜单"""
        context_menu = tk.Menu(self.root, tearoff=0)
        context_menu.add_command(label="显示控制面板", command=self.show_controls)
        context_menu.add_separator()
        context_menu.add_command(label="置顶窗口", command=self.toggle_topmost)
        context_menu.add_command(label="重新连接", command=self.reconnect)
        context_menu.add_separator()
        context_menu.add_command(label="关闭窗口", command=self.close_window)
        
        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()
            
    def toggle_controls(self):
        """切换控制面板显示状态"""
        if self.control_frame.winfo_viewable():
            self.hide_controls()
        else:
            self.show_controls()
            
    def show_controls(self):
        """显示控制面板"""
        # 计算控制面板位置（在主窗口右侧）
        x = self.root.winfo_x() + self.root.winfo_width() + 10
        y = self.root.winfo_y()

        # 控制面板参数设置区
        if not hasattr(self, 'param_frame'):
            self.param_frame = tk.Frame(self.control_frame, bg="#333333")
            self.param_frame.pack(fill=tk.X, padx=10, pady=2)

            # 背景色设置
            tk.Label(self.param_frame, text="字幕背景色:", fg="white", bg="#333333").pack(side=tk.LEFT)
            self.bg_color_var = tk.StringVar(value=self.config.get('bg_color', '#ffffff'))
            bg_entry = tk.Entry(self.param_frame, textvariable=self.bg_color_var, width=10)
            bg_entry.pack(side=tk.LEFT, padx=2)
            tk.Button(self.param_frame, text="应用", command=self.apply_bg_color, bg="#555555", fg="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

            # 字体大小设置
            tk.Label(self.param_frame, text="字体大小:", fg="white", bg="#333333").pack(side=tk.LEFT, padx=(10,0))
            self.font_size_var = tk.StringVar(value=str(self.config.get('subtitle_font_size', '24px')).replace('px',''))
            font_entry = tk.Entry(self.param_frame, textvariable=self.font_size_var, width=5)
            font_entry.pack(side=tk.LEFT, padx=2)
            tk.Button(self.param_frame, text="应用", command=self.apply_font_size, bg="#555555", fg="white", relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        self.control_frame.place(x=x, y=y)
        self.control_frame.lift()

    def apply_bg_color(self):
        color = self.bg_color_var.get()
        self.config['bg_color'] = color
        self.apply_config()

    def apply_font_size(self):
        size = self.font_size_var.get()
        if size.isdigit():
            self.config['subtitle_font_size'] = f"{size}px"
            self.apply_config()
        
    def hide_controls(self):
        """隐藏控制面板"""
        self.control_frame.place_forget()
        
    def update_alpha(self, value):
        """更新窗口透明度"""
        self.root.attributes('-alpha', float(value))
        
    def toggle_topmost(self):
        """切换窗口置顶状态"""
        topmost = self.topmost_var.get()
        self.root.attributes('-topmost', topmost)
        
    def update_status(self, text, color):
        """更新连接状态"""
        if hasattr(self, 'status_label'):
            self.status_label.configure(text=text, fg=color)
            
    def reconnect(self):
        """重新连接"""
        try:
            if self.socket_client.connected:
                self.socket_client.disconnect()
            time.sleep(1)
            self.connect_to_server()
        except Exception as e:
            self.update_status(f"重连失败: {str(e)}", "red")
            
    def show_help(self):
        """显示帮助信息"""
        help_text = """
字幕显示窗口 - 帮助信息

快捷键:
• ESC - 显示/隐藏控制面板
• F1 - 显示此帮助信息

鼠标操作:
• 标题栏拖拽 - 移动窗口位置
• 字幕区域拖拽 - 也可移动窗口位置
• 右键点击 - 显示右键菜单

功能说明:
• 窗口支持置顶显示
• 可调节透明度
• 自动连接字幕服务器
• 实时同步配置更新
• 在任务栏显示标题
• 完全支持直播工具捕捉（如OBS）
"""
        messagebox.showinfo("帮助信息", help_text)
        
    def close_window(self):
        """关闭窗口"""
        try:
            if self.socket_client and self.socket_client.connected:
                self.socket_client.disconnect()
        except:
            pass
        self.root.quit()
        self.root.destroy()
        
    def run(self):
        """运行窗口"""
        # 启动Socket连接
        threading.Thread(target=self.connect_to_server, daemon=True).start()
        
        # 启动主循环
        self.root.mainloop()

def main():
    """主函数"""
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    try:
        app = DesktopCaptionWindow()
        app.run()
    except KeyboardInterrupt:
        logging.info("程序被用户中断")
    except Exception as e:
        logging.error(f"程序运行异常: {e}")
        messagebox.showerror("错误", f"程序运行异常: {e}")

if __name__ == "__main__":
    main()