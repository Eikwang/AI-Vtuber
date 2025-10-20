import json
import os
from datetime import datetime
from typing import Dict, Optional
from enum import Enum
import asyncio

class MonitorStatus(Enum):
    """监控状态枚举"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"
    RECONNECTING = "reconnecting"

class MonitorManager:
    """监控状态管理器"""
    
    def __init__(self, data_file: str = "monitor_status.json"):
        self.data_file = data_file
        self.sessions = {}
        self.broadcast_callback = None
        self.load_status()
    
    def set_broadcast_callback(self, callback):
        """设置广播回调函数"""
        self.broadcast_callback = callback
    
    def load_status(self):
        """从文件加载监控状态"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.sessions = data.get('sessions', {})
            else:
                self.sessions = {}
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading monitor status: {e}")
            self.sessions = {}
    
    def save_status(self):
        """保存监控状态到文件"""
        try:
            data = {
                "version": "1.0",
                "sessions": self.sessions
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving monitor status: {e}")
    
    def create_session(self, url_id: str, browser_tab_id: str = None) -> Dict:
        """创建新的监控会话"""
        session = {
            "status": MonitorStatus.STARTING.value,
            "browser_tab_id": browser_tab_id,
            "start_time": datetime.now().isoformat(),
            "last_heartbeat": datetime.now().isoformat(),
            "error_message": None,
            "reconnect_count": 0,
            "message_count": 0,
            "error_count": 0,
            "cpu_usage": 0.0,
            "memory_usage": 0.0
        }
        
        self.sessions[url_id] = session
        self.save_status()
        return session
    
    def update_session_status(self, url_id: str, status: MonitorStatus, 
                            error_message: str = None):
        """更新会话状态"""
        if url_id in self.sessions:
            self.sessions[url_id]["status"] = status.value
            self.sessions[url_id]["last_heartbeat"] = datetime.now().isoformat()
            
            if error_message:
                self.sessions[url_id]["error_message"] = error_message
            elif status != MonitorStatus.ERROR:
                self.sessions[url_id]["error_message"] = None
            
            self.save_status()
            
            # 触发广播
            if self.broadcast_callback:
                asyncio.create_task(self.broadcast_callback({
                    "type": "status_update",
                    "url_id": url_id,
                    "session": self.sessions[url_id]
                }))
    
    def update_heartbeat(self, url_id: str):
        """更新心跳时间"""
        if url_id in self.sessions:
            self.sessions[url_id]["last_heartbeat"] = datetime.now().isoformat()
            self.save_status()
    
    def increment_message_count(self, url_id: str):
        """增加消息计数"""
        if url_id in self.sessions:
            self.sessions[url_id]["message_count"] += 1
            self.sessions[url_id]["last_heartbeat"] = datetime.now().isoformat()
            self.save_status()
    
    def increment_reconnect_count(self, url_id: str):
        """增加重连计数"""
        if url_id in self.sessions:
            self.sessions[url_id]["reconnect_count"] += 1
            self.sessions[url_id]["status"] = MonitorStatus.RECONNECTING.value
            self.sessions[url_id]["last_heartbeat"] = datetime.now().isoformat()
            self.save_status()
    
    def increment_error_count(self, url_id: str):
        """增加错误计数"""
        if url_id in self.sessions:
            self.sessions[url_id]["error_count"] = self.sessions[url_id].get("error_count", 0) + 1
            self.sessions[url_id]["last_heartbeat"] = datetime.now().isoformat()
            self.save_status()
    
    def update_resource_usage(self, url_id: str, cpu_usage: float, memory_usage: float):
        """更新资源使用情况"""
        if url_id in self.sessions:
            self.sessions[url_id]["cpu_usage"] = cpu_usage
            self.sessions[url_id]["memory_usage"] = memory_usage
            self.sessions[url_id]["last_heartbeat"] = datetime.now().isoformat()
            self.save_status()
    
    def get_session(self, url_id: str) -> Optional[Dict]:
        """获取会话信息"""
        return self.sessions.get(url_id)
    
    def get_session_status(self, url_id: str) -> Optional[str]:
        """获取会话状态"""
        session = self.sessions.get(url_id)
        return session.get("status") if session else None
    
    def get_all_sessions(self) -> Dict:
        """获取所有会话信息"""
        return self.sessions.copy()
    
    def remove_session(self, url_id: str) -> bool:
        """移除会话"""
        if url_id in self.sessions:
            del self.sessions[url_id]
            self.save_status()
            return True
        return False
    
    def get_running_sessions(self) -> Dict:
        """获取所有运行中的会话"""
        return {
            url_id: session for url_id, session in self.sessions.items()
            if session["status"] == MonitorStatus.RUNNING.value
        }
    
    def get_error_sessions(self) -> Dict:
        """获取所有错误状态的会话"""
        return {
            url_id: session for url_id, session in self.sessions.items()
            if session["status"] == MonitorStatus.ERROR.value
        }
    
    def cleanup_old_sessions(self, max_age_hours: int = 24):
        """清理过期的会话"""
        from datetime import timedelta
        
        current_time = datetime.now()
        sessions_to_remove = []
        
        for url_id, session in self.sessions.items():
            try:
                last_heartbeat = datetime.fromisoformat(session["last_heartbeat"])
                if current_time - last_heartbeat > timedelta(hours=max_age_hours):
                    if session["status"] in [MonitorStatus.STOPPED.value, MonitorStatus.ERROR.value]:
                        sessions_to_remove.append(url_id)
            except (ValueError, KeyError):
                # 如果时间格式有问题，也清理掉
                sessions_to_remove.append(url_id)
        
        for url_id in sessions_to_remove:
            del self.sessions[url_id]
        
        if sessions_to_remove:
            self.save_status()
        
        return len(sessions_to_remove)
    
    def get_session_statistics(self) -> Dict:
        """获取会话统计信息"""
        stats = {
            "total_sessions": len(self.sessions),
            "running_count": 0,
            "error_count": 0,
            "stopped_count": 0,
            "total_messages": 0,
            "total_reconnects": 0,
            "avg_cpu_usage": 0.0,
            "avg_memory_usage": 0.0
        }
        
        if not self.sessions:
            return stats
        
        cpu_total = 0.0
        memory_total = 0.0
        
        for session in self.sessions.values():
            status = session["status"]
            if status == MonitorStatus.RUNNING.value:
                stats["running_count"] += 1
            elif status == MonitorStatus.ERROR.value:
                stats["error_count"] += 1
            elif status == MonitorStatus.STOPPED.value:
                stats["stopped_count"] += 1
            
            stats["total_messages"] += session.get("message_count", 0)
            stats["total_reconnects"] += session.get("reconnect_count", 0)
            cpu_total += session.get("cpu_usage", 0.0)
            memory_total += session.get("memory_usage", 0.0)
        
        stats["avg_cpu_usage"] = cpu_total / len(self.sessions)
        stats["avg_memory_usage"] = memory_total / len(self.sessions)
        
        return stats