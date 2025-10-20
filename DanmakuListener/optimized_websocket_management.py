#!/usr/bin/env python3
"""
优化的WebSocket连接管理
解决连接泄漏和消息积累问题
"""

import asyncio
import weakref
import time
import json
from collections import deque
from typing import Dict, Set, Optional, List
from dataclasses import dataclass
from enum import Enum

class ConnectionState(Enum):
    """连接状态枚举"""
    ACTIVE = "active"
    IDLE = "idle"
    CLOSING = "closing"
    DEAD = "dead"

@dataclass
class ConnectionInfo:
    """连接信息"""
    websocket: object
    connected_at: float
    last_activity: float
    state: ConnectionState
    ip_address: str = ""
    user_agent: str = ""
    message_count: int = 0

class OptimizedWebSocketManager:
    """优化的WebSocket连接管理器"""
    
    def __init__(self, max_clients=100, message_queue_size=1000, enable_batching=True):
        # 使用WeakSet自动清理断开的连接
        self.connected_clients: Set = weakref.WeakSet()
        
        # 连接信息映射
        self.connection_info: Dict[object, ConnectionInfo] = {}
        
        # 限制消息队列大小，避免无限增长
        self.message_queue = deque(maxlen=message_queue_size)
        
        # 消息批处理队列
        self.pending_messages = deque(maxlen=50) if enable_batching else None
        self.batch_send_task = None
        self.enable_batching = enable_batching
        
        # 连接统计和清理
        self.max_clients = max_clients
        self.last_cleanup = time.time()
        self.cleanup_interval = 30  # 30秒清理一次
        self.idle_timeout = 300  # 5分钟空闲超时
        
        # 任务追踪，避免任务泄漏
        self.active_tasks: Set[asyncio.Task] = set()
        
        # 统计信息
        self.stats = {
            'total_connections': 0,
            'active_connections': 0,
            'messages_sent': 0,
            'messages_failed': 0,
            'cleanup_runs': 0
        }
        
        # 启动批量发送任务（延迟到事件循环可用时）
        if self.enable_batching:
            self.batch_send_task = None  # 初始为None，稍后启动
    
    def _ensure_batch_sender_started(self):
        """确保批量发送器已启动"""
        if self.enable_batching and (self.batch_send_task is None or self.batch_send_task.done()):
            try:
                self.batch_send_task = asyncio.create_task(self._batch_sender_loop())
                self.active_tasks.add(self.batch_send_task)
            except RuntimeError:
                # 如果没有运行事件循环，稍后再试
                pass
    
    async def _batch_sender_loop(self):
        """批量消息发送循环"""
        while True:
            try:
                await asyncio.sleep(0.05)  # 50ms批量间隔
                if self.pending_messages:
                    messages_to_send = []
                    while self.pending_messages and len(messages_to_send) < 10:
                        messages_to_send.append(self.pending_messages.popleft())
                    
                    if messages_to_send:
                        combined_message = json.dumps({
                            "type": "batch",
                            "messages": messages_to_send
                        })
                        await self._direct_broadcast(combined_message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"批量发送器异常: {e}")
                await asyncio.sleep(1)
    
    async def add_client(self, websocket, client_ip="", user_agent=""):
        """添加客户端连接"""
        # 确保批量发送器已启动
        self._ensure_batch_sender_started()
        
        # 检查连接数量限制
        if len(self.connected_clients) >= self.max_clients:
            await self._cleanup_dead_connections()
            
            if len(self.connected_clients) >= self.max_clients:
                raise ConnectionError(f"连接数量已达上限 {self.max_clients}")
        
        # 添加连接
        self.connected_clients.add(websocket)
        
        # 记录连接信息
        current_time = time.time()
        self.connection_info[websocket] = ConnectionInfo(
            websocket=websocket,
            connected_at=current_time,
            last_activity=current_time,
            state=ConnectionState.ACTIVE,
            ip_address=client_ip,
            user_agent=user_agent,
            message_count=0
        )
        
        # 更新统计
        self.stats['total_connections'] += 1
        self.stats['active_connections'] = len(self.connected_clients)
        
        print(f"客户端已连接 [IP: {client_ip}]，当前连接数: {len(self.connected_clients)}")
    
    async def remove_client(self, websocket):
        """移除客户端连接"""
        try:
            # 更新连接状态
            if websocket in self.connection_info:
                self.connection_info[websocket].state = ConnectionState.CLOSING
                del self.connection_info[websocket]
            
            self.connected_clients.discard(websocket)
            
            if not websocket.closed:
                await websocket.close()
                
            # 更新统计
            self.stats['active_connections'] = len(self.connected_clients)
            
        except Exception as e:
            print(f"移除客户端时出错: {e}")
    
    async def broadcast_optimized(self, message: str, use_batching=None):
        """优化的消息广播"""
        if not self.connected_clients:
            return
        
        # 如果启用批处理且消息适合批处理
        if (use_batching is None and self.enable_batching) or use_batching:
            try:
                message_data = json.loads(message) if isinstance(message, str) else message
                if isinstance(message_data, dict) and message_data.get('type') in ['danmaku', 'comment', 'gift']:
                    self.pending_messages.append(message_data)
                    return
            except (json.JSONDecodeError, AttributeError):
                pass
        
        # 直接广播
        await self._direct_broadcast(message)
    
    async def _direct_broadcast(self, message: str):
        """直接广播消息（不使用批处理）"""
        if not self.connected_clients:
            return
        
        # 定期清理死连接
        current_time = time.time()
        if current_time - self.last_cleanup > self.cleanup_interval:
            await self._cleanup_dead_connections()
            await self._cleanup_idle_connections()
            self.last_cleanup = current_time
        
        # 批量发送，减少异步任务数量
        send_tasks = []
        dead_clients = []
        
        for client in list(self.connected_clients):
            if client.closed:
                dead_clients.append(client)
                continue
            
            # 更新活动时间
            if client in self.connection_info:
                self.connection_info[client].last_activity = current_time
                self.connection_info[client].message_count += 1
            
            # 创建发送任务
            task = asyncio.create_task(self._safe_send(client, message))
            send_tasks.append(task)
            self.active_tasks.add(task)
        
        # 清理死连接
        for client in dead_clients:
            await self._remove_dead_client(client)
        
        # 等待所有发送完成，设置超时
        if send_tasks:
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*send_tasks, return_exceptions=True),
                    timeout=3.0
                )
                
                # 统计发送结果
                for result in results:
                    if isinstance(result, Exception):
                        self.stats['messages_failed'] += 1
                    else:
                        self.stats['messages_sent'] += 1
                        
            except asyncio.TimeoutError:
                print("消息发送超时，取消剩余任务")
                for task in send_tasks:
                    if not task.done():
                        task.cancel()
                        self.stats['messages_failed'] += 1
        
        # 清理完成的任务
        self.active_tasks = {task for task in self.active_tasks if not task.done()}
    
    async def _safe_send(self, client, message: str):
        """安全发送消息"""
        try:
            await client.send_str(message)
            return True
        except Exception as e:
            # 发送失败，标记连接为死连接
            await self._remove_dead_client(client)
            return False
    
    async def _remove_dead_client(self, client):
        """移除死连接"""
        try:
            if client in self.connection_info:
                self.connection_info[client].state = ConnectionState.DEAD
                del self.connection_info[client]
            
            self.connected_clients.discard(client)
            
            if not client.closed:
                try:
                    await client.close()
                except:
                    pass
        except Exception as e:
            print(f"移除死连接时出错: {e}")
    
    async def _cleanup_dead_connections(self):
        """清理死连接"""
        dead_clients = []
        for client in list(self.connected_clients):
            try:
                if client.closed or client._writer is None:
                    dead_clients.append(client)
                elif hasattr(client._writer, 'transport') and client._writer.transport.is_closing():
                    dead_clients.append(client)
            except Exception:
                dead_clients.append(client)
        
        for client in dead_clients:
            await self._remove_dead_client(client)
        
        if dead_clients:
            self.stats['cleanup_runs'] += 1
            self.stats['active_connections'] = len(self.connected_clients)
            print(f"清理了 {len(dead_clients)} 个死连接，当前连接数: {len(self.connected_clients)}")
    
    async def _cleanup_idle_connections(self):
        """清理空闲连接"""
        current_time = time.time()
        idle_clients = []
        
        for client, info in list(self.connection_info.items()):
            if current_time - info.last_activity > self.idle_timeout:
                idle_clients.append(client)
        
        for client in idle_clients:
            print(f"清理空闲连接: 空闲时间 {current_time - self.connection_info[client].last_activity:.1f} 秒")
            await self._remove_dead_client(client)
    
    def get_statistics(self) -> Dict:
        """获取连接池统计信息"""
        active_info = []
        for client, info in self.connection_info.items():
            if info.state == ConnectionState.ACTIVE:
                active_info.append({
                    'ip': info.ip_address,
                    'connected_duration': time.time() - info.connected_at,
                    'last_activity': time.time() - info.last_activity,
                    'message_count': info.message_count
                })
        
        return {
            **self.stats,
            'current_connections': len(self.connected_clients),
            'max_clients': self.max_clients,
            'message_queue_size': len(self.message_queue),
            'pending_messages': len(self.pending_messages) if self.pending_messages else 0,
            'active_tasks': len(self.active_tasks),
            'connection_details': active_info
        }
    
    async def cleanup_all(self):
        """清理所有资源"""
        # 停止批量发送任务
        if self.batch_send_task and not self.batch_send_task.done():
            self.batch_send_task.cancel()
            try:
                await self.batch_send_task
            except (asyncio.CancelledError, Exception):
                pass
        
        # 关闭所有连接
        close_tasks = []
        for client in list(self.connected_clients):
            if not client.closed:
                close_tasks.append(asyncio.create_task(client.close()))
        
        if close_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*close_tasks, return_exceptions=True), timeout=5.0)
            except asyncio.TimeoutError:
                print("关闭WebSocket连接超时，强制清理")
        
        # 取消所有活跃任务
        cancelled_tasks = []
        for task in list(self.active_tasks):
            if not task.done():
                task.cancel()
                cancelled_tasks.append(task)
        
        # 等待任务完成
        if cancelled_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*cancelled_tasks, return_exceptions=True), timeout=3.0)
            except asyncio.TimeoutError:
                print("取消任务超时，继续清理")
        
        # 清理所有数据结构
        self.connected_clients.clear()
        self.connection_info.clear()
        self.active_tasks.clear()
        self.message_queue.clear()
        if self.pending_messages:
            self.pending_messages.clear()
        
        print(f"WebSocket管理器已完全清理 - 统计信息: {self.get_statistics()}")

# 使用示例
"""
# 初始化优化的管理器（启用批处理）
ws_manager = OptimizedWebSocketManager(
    max_clients=50, 
    message_queue_size=500,
    enable_batching=True
)

async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    client_ip = request.remote
    user_agent = request.headers.get('User-Agent', 'Unknown')
    
    try:
        await ws_manager.add_client(ws, client_ip, user_agent)
        # ... 处理消息 ...
    finally:
        await ws_manager.remove_client(ws)
    
    return ws

async def broadcast(message):
    # 使用批处理（适合高频消息）
    await ws_manager.broadcast_optimized(message, use_batching=True)
    
    # 或者直接发送（适合重要消息）
    await ws_manager.broadcast_optimized(message, use_batching=False)

# 获取统计信息
stats = ws_manager.get_statistics()
print(f"当前连接数: {stats['current_connections']}")
print(f"发送成功率: {stats['messages_sent']/(stats['messages_sent']+stats['messages_failed'])*100:.1f}%")
"""