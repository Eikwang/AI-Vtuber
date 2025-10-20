import asyncio
import websockets
import json
import logging
from typing import Optional, Callable, Dict, Any
from datetime import datetime

class LiveCompanionClient:
    """
    直播伴侣客户端WebSocket连接管理器
    连接到WssBarrageServer.exe的8878端口，接收DouyinBarrageGrab消息
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8878):
        self.host = host
        self.port = port
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.is_connected = False
        self.is_running = False
        self.message_handler: Optional[Callable] = None
        self.reconnect_interval = 5  # 重连间隔（秒）
        self.max_reconnect_attempts = 10
        self.reconnect_attempts = 0
        
        # 设置日志
        self.logger = logging.getLogger(f"LiveCompanionClient_{port}")
        
    def set_message_handler(self, handler: Callable[[Dict[str, Any]], None]):
        """设置消息处理回调函数"""
        self.message_handler = handler
        
    async def connect(self) -> bool:
        """连接到直播伴侣WebSocket服务器"""
        try:
            uri = f"ws://{self.host}:{self.port}"
            self.logger.info(f"正在连接到直播伴侣服务器: {uri}")
            
            self.websocket = await websockets.connect(
                uri,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10
            )
            
            self.is_connected = True
            self.reconnect_attempts = 0
            self.logger.info(f"成功连接到直播伴侣服务器: {uri}")
            return True
            
        except Exception as e:
            self.logger.error(f"连接直播伴侣服务器失败: {e}")
            self.is_connected = False
            return False
    
    async def disconnect(self):
        """断开WebSocket连接"""
        self.is_running = False
        if self.websocket and not self.websocket.closed:
            await self.websocket.close()
        self.is_connected = False
        self.logger.info("已断开直播伴侣服务器连接")
    
    async def listen(self):
        """监听消息的主循环"""
        self.is_running = True
        
        while self.is_running:
            try:
                if not self.is_connected:
                    if await self.connect():
                        self.logger.info("开始监听直播伴侣消息...")
                    else:
                        await self._handle_reconnect()
                        continue
                
                # 监听消息
                async for message in self.websocket:
                    if not self.is_running:
                        break
                        
                    try:
                        await self._process_message(message)
                    except Exception as e:
                        self.logger.error(f"处理消息时出错: {e}")
                        
            except websockets.exceptions.ConnectionClosed:
                self.logger.warning("直播伴侣连接已断开")
                self.is_connected = False
                if self.is_running:
                    await self._handle_reconnect()
                    
            except Exception as e:
                self.logger.error(f"监听过程中出现异常: {e}")
                self.is_connected = False
                if self.is_running:
                    await self._handle_reconnect()
    
    async def _process_message(self, message):
        """处理接收到的消息"""
        try:
            # 解析JSON消息
            if isinstance(message, str):
                data = json.loads(message)
            else:
                data = json.loads(message.decode('utf-8'))
            
            # 添加接收时间戳
            data['received_at'] = datetime.now().isoformat()
            
            self.logger.debug(f"收到直播伴侣消息: Type={data.get('Type')}, ProcessName={data.get('ProcessName')}")
            
            # 调用消息处理器
            if self.message_handler:
                await self.message_handler(data)
            else:
                self.logger.warning("未设置消息处理器，消息被忽略")
                
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败: {e}, 原始消息: {message}")
        except Exception as e:
            self.logger.error(f"消息处理异常: {e}")
    
    async def _handle_reconnect(self):
        """处理重连逻辑"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error(f"重连尝试次数已达上限({self.max_reconnect_attempts})，停止重连")
            self.is_running = False
            return
        
        self.reconnect_attempts += 1
        self.logger.info(f"等待 {self.reconnect_interval} 秒后进行第 {self.reconnect_attempts} 次重连...")
        await asyncio.sleep(self.reconnect_interval)
    
    async def start(self):
        """启动客户端连接和监听"""
        self.is_running = True
        self.logger.info("启动直播伴侣客户端...")
        
        while self.is_running:
            try:
                if await self.connect():
                    await self.listen()
                else:
                    await self._handle_reconnect()
            except Exception as e:
                self.logger.error(f"客户端运行异常: {e}")
                await self._handle_reconnect()
    
    def get_status(self) -> Dict[str, Any]:
        """获取连接状态信息"""
        return {
            "connected": self.is_connected,
            "running": self.is_running,
            "host": self.host,
            "port": self.port,
            "reconnect_attempts": self.reconnect_attempts,
            "max_reconnect_attempts": self.max_reconnect_attempts
        }