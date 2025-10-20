import asyncio
import websockets
import json
import logging
import time
from typing import Optional, Dict, Any
import traceback
import asyncio

class AIVtuberWebSocketClient:
    """AI-VTUBER WebSocket客户端，用于替代API转发"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.running = False
        self.reconnect_task: Optional[asyncio.Task] = None
        self.stats = {
            "total_sent": 0,
            "success_count": 0,
            "error_count": 0,
            "last_error": None,
            "connected": False,
            "last_connect_time": None,
            "reconnect_attempts": 0
        }
        
        # 从配置中获取连接参数
        self.host = config.get('host', '127.0.0.1')
        self.port = config.get('port', 8765)
        self.path = config.get('path', '/danmaku')
        self.auto_reconnect = config.get('auto_reconnect', True)
        self.reconnect_interval = config.get('reconnect_interval', 5)
        self.max_reconnect_attempts = config.get('max_reconnect_attempts', 10)
        self.connection_timeout = config.get('connection_timeout', 10)
        
        self.uri = f"ws://{self.host}:{self.port}{self.path}"
        
        logging.info(f"AI-VTUBER WebSocket客户端初始化: {self.uri}")
    
    async def connect(self) -> bool:
        """连接到AI-VTUBER WebSocket服务器"""
        try:
            logging.info(f"正在连接到AI-VTUBER WebSocket服务器: {self.uri}")
            
            # 设置连接超时
            self.websocket = await asyncio.wait_for(
                websockets.connect(
                    self.uri,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=10
                ),
                timeout=self.connection_timeout
            )
            
            self.stats["connected"] = True
            self.stats["last_connect_time"] = time.time()
            self.stats["reconnect_attempts"] = 0
            
            logging.info("AI-VTUBER WebSocket连接成功")
            return True
            
        except asyncio.TimeoutError:
            error_msg = f"连接超时 ({self.connection_timeout}秒)"
            self.stats["last_error"] = error_msg
            logging.error(f"AI-VTUBER WebSocket连接失败: {error_msg}")
            return False
            
        except Exception as e:
            error_msg = f"连接异常: {str(e)}"
            self.stats["last_error"] = error_msg
            logging.error(f"AI-VTUBER WebSocket连接失败: {error_msg}")
            return False
    
    async def disconnect(self):
        """断开WebSocket连接"""
        if self.websocket and not self.websocket.closed:
            try:
                await self.websocket.close()
                logging.info("AI-VTUBER WebSocket连接已断开")
            except Exception as e:
                logging.error(f"断开AI-VTUBER WebSocket连接时出错: {e}")
        
        self.stats["connected"] = False
        self.websocket = None
    
    async def send_message(self, message_data: Dict[str, Any]) -> bool:
        """发送消息到AI-VTUBER WebSocket服务器"""
        if not self.config.get('enabled', False):
            return True
        
        if not self.websocket or self.websocket.closed:
            logging.warning("AI-VTUBER WebSocket未连接，尝试重连")
            if not await self.connect():
                return False
        
        try:
            # 转换消息格式为AI-VTUBER期望的格式
            formatted_message = self._format_message(message_data)
            message_json = json.dumps(formatted_message, ensure_ascii=False)
            
            await self.websocket.send(message_json)
            
            self.stats["total_sent"] += 1
            self.stats["success_count"] += 1
            
            logging.debug(f"消息已发送到AI-VTUBER: {formatted_message.get('type', 'unknown')}")
            return True
            
        except websockets.exceptions.ConnectionClosed:
            self.stats["connected"] = False
            self.stats["error_count"] += 1
            self.stats["last_error"] = "连接已关闭"
            logging.warning("AI-VTUBER WebSocket连接已关闭")
            
            # 触发重连
            if self.auto_reconnect:
                asyncio.create_task(self._reconnect())
            
            return False
            
        except Exception as e:
            self.stats["error_count"] += 1
            self.stats["last_error"] = str(e)
            logging.error(f"发送消息到AI-VTUBER失败: {e}")
            return False
    
    def _format_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """将消息格式化为AI-VTUBER期望的格式"""
        msg_type = message_data.get('type', 'unknown')
        data = message_data.get('data', message_data)
        
        # 将danmaku类型转换为AI-VTUBER期望的comment类型
        if msg_type == 'danmaku':
            msg_type = 'comment'
        
        # 标准化消息格式
        formatted = {
            'type': msg_type,
            'data': {
                'username': data.get('username', ''),
                'content': data.get('content', ''),
                'platform': data.get('platform', 'unknown'),
                'timestamp': data.get('timestamp', time.time()),
                'uid': data.get('user_id', data.get('uid', ''))
            }
        }
        
        # 根据消息类型添加特定字段
        if msg_type == 'gift':
            formatted['data'].update({
                'gift_name': data.get('giftName', data.get('gift_name', '')),
                'gift_num': data.get('giftCount', data.get('gift_count', data.get('gift_num', 1))),
                'price': data.get('giftPrice', data.get('price', 0))
            })
        elif msg_type == 'super_chat':
            formatted['data'].update({
                'price': data.get('price', 0)
            })
        elif msg_type == 'like':
            formatted['data'].update({
                'like_count': data.get('likeCount', data.get('like_count', 1))
            })
        
        return formatted
    
    async def _reconnect(self):
        """自动重连逻辑"""
        if self.reconnect_task and not self.reconnect_task.done():
            return  # 已有重连任务在进行
        
        self.reconnect_task = asyncio.create_task(self._do_reconnect())
    
    async def _do_reconnect(self):
        """执行重连"""
        while (self.auto_reconnect and 
               self.stats["reconnect_attempts"] < self.max_reconnect_attempts and
               self.running):
            
            self.stats["reconnect_attempts"] += 1
            
            logging.info(f"尝试重连AI-VTUBER WebSocket (第{self.stats['reconnect_attempts']}次)")
            
            await asyncio.sleep(self.reconnect_interval)
            
            if await self.connect():
                logging.info("AI-VTUBER WebSocket重连成功")
                return
        
        if self.stats["reconnect_attempts"] >= self.max_reconnect_attempts:
            logging.error(f"AI-VTUBER WebSocket重连失败，已达到最大重试次数 ({self.max_reconnect_attempts})")
    
    async def start(self):
        """启动WebSocket客户端"""
        self.running = True
        if self.config.get('enabled', False):
            await self.connect()
    
    async def stop(self):
        """停止WebSocket客户端"""
        self.running = False
        
        # 取消重连任务
        if self.reconnect_task and not self.reconnect_task.done():
            self.reconnect_task.cancel()
        
        await self.disconnect()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取连接统计信息"""
        return self.stats.copy()
    
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return (self.websocket is not None and 
                not self.websocket.closed and 
                self.stats["connected"])