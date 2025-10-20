import asyncio
import json
import websockets
import logging
from typing import Set, Optional
from utils.config import Config

# 获取logger实例
logger = logging.getLogger(__name__)

class DanmakuWebSocketServer:
    """
    弹幕WebSocket服务器
    接收来自DanmakuListener的弹幕消息并转发给AI-VTUBER处理
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, path: str = "/danmaku"):
        self.host = host
        self.port = port
        self.path = path
        self.clients: Set[websockets.WebSocketServerProtocol] = set()
        self.server: Optional[websockets.WebSocketServer] = None
        self.message_handler = None
        self.running = False
        
    def set_message_handler(self, handler):
        """设置消息处理器"""
        self.message_handler = handler
        
    async def handle_client(self, websocket, path):
        """处理客户端连接"""
        client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"弹幕WebSocket客户端连接: {client_info}, 路径: {path}")
        
        # 检查路径是否匹配
        if path != self.path:
            logger.warning(f"WebSocket路径不匹配: 期望 {self.path}, 实际 {path}")
            await websocket.close(code=1008, reason="Invalid path")
            return
        
        self.clients.add(websocket)
        try:
            async for message in websocket:
                try:
                    # 解析JSON消息
                    data = json.loads(message)
                    logger.debug(f"收到弹幕消息: {data.get('type', 'unknown')} - {data.get('data', {}).get('content', '')}")
                    
                    # 转发给消息处理器
                    if self.message_handler:
                        await self.message_handler(data)
                    
                    # 发送确认响应
                    response = {
                        "type": "ack",
                        "status": "success",
                        "message": "消息已接收"
                    }
                    await websocket.send(json.dumps(response))
                    
                except json.JSONDecodeError as e:
                    logger.error(f"弹幕消息JSON解析失败: {e}")
                    error_response = {
                        "type": "error",
                        "status": "failed",
                        "message": "消息格式错误"
                    }
                    await websocket.send(json.dumps(error_response))
                    
                except Exception as e:
                    logger.error(f"处理弹幕消息异常: {e}")
                    
        except websockets.exceptions.ConnectionClosedError:
            logger.info(f"弹幕WebSocket客户端断开: {client_info}")
        except Exception as e:
            logger.error(f"弹幕WebSocket连接异常: {e}")
        finally:
            self.clients.discard(websocket)
            logger.info(f"弹幕WebSocket客户端移除: {client_info}")
            
    async def start(self):
        """启动WebSocket服务器"""
        if self.running:
            logger.warning("弹幕WebSocket服务器已在运行")
            return
            
        try:
            self.server = await websockets.serve(
                self.handle_client,
                self.host,
                self.port,
                ping_interval=30,
                ping_timeout=10,
                max_size=16*1024*1024  # 16MB
            )
            self.running = True
            logger.info(f"弹幕WebSocket服务器启动成功: ws://{self.host}:{self.port}{self.path}")
            
        except Exception as e:
            logger.error(f"弹幕WebSocket服务器启动失败: {e}")
            raise
            
    async def stop(self):
        """停止WebSocket服务器"""
        if not self.running:
            return
            
        try:
            # 关闭所有客户端连接
            if self.clients:
                await asyncio.gather(
                    *[client.close() for client in self.clients.copy()],
                    return_exceptions=True
                )
                self.clients.clear()
                
            # 关闭服务器
            if self.server:
                self.server.close()
                await self.server.wait_closed()
                
            self.running = False
            logger.info("弹幕WebSocket服务器已停止")
            
        except Exception as e:
            logger.error(f"停止弹幕WebSocket服务器异常: {e}")
            
    def get_status(self) -> dict:
        """获取服务器状态"""
        return {
            "running": self.running,
            "host": self.host,
            "port": self.port,
            "path": self.path,
            "clients_count": len(self.clients),
            "clients": [f"{client.remote_address[0]}:{client.remote_address[1]}" 
                       for client in self.clients if not client.closed]
        }
        
    async def broadcast_message(self, message: dict):
        """向所有客户端广播消息"""
        if not self.clients:
            return
            
        message_str = json.dumps(message)
        disconnected_clients = set()
        
        for client in self.clients.copy():
            try:
                if not client.closed:
                    await client.send(message_str)
                else:
                    disconnected_clients.add(client)
            except Exception as e:
                logger.warning(f"向客户端发送消息失败: {e}")
                disconnected_clients.add(client)
                
        # 清理断开的连接
        for client in disconnected_clients:
            self.clients.discard(client)


# 全局实例
_danmaku_websocket_server: Optional[DanmakuWebSocketServer] = None

def get_danmaku_websocket_server() -> DanmakuWebSocketServer:
    """获取弹幕WebSocket服务器实例"""
    global _danmaku_websocket_server
    
    if _danmaku_websocket_server is None:
        # 从配置文件读取设置
        config = Config("config.json")
        ws_config = config.get("danmaku_websocket", {})
        
        host = ws_config.get("host", "127.0.0.1")
        port = ws_config.get("port", 8765)
        path = ws_config.get("path", "/danmaku")
        
        _danmaku_websocket_server = DanmakuWebSocketServer(host, port, path)
        
    return _danmaku_websocket_server

def reset_danmaku_websocket_server():
    """重置弹幕WebSocket服务器实例"""
    global _danmaku_websocket_server
    _danmaku_websocket_server = None