"""
状态持久化管理器
负责在Chromium重启过程中保持和恢复系统状态
确保重启后能无缝继续之前的监听任务
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict, field
import pickle
import sqlite3
from contextlib import asynccontextmanager

@dataclass
class MonitoringSession:
    """监控会话数据类"""
    url_id: str
    url: str
    script_name: str
    start_time: float
    last_activity: float
    status: str = "active"  # active, paused, stopped
    cookies: Optional[List[Dict]] = None
    local_storage: Optional[Dict] = None
    session_storage: Optional[Dict] = None
    page_state: Optional[Dict] = None
    injection_state: Optional[Dict] = None
    error_count: int = 0
    success_count: int = 0
    metadata: Dict = field(default_factory=dict)

@dataclass
class SystemState:
    """系统状态数据类"""
    timestamp: float
    browser_config: Dict
    monitoring_sessions: List[MonitoringSession]
    global_settings: Dict
    performance_metrics: Dict
    restart_context: Dict = field(default_factory=dict)

class StatePersistenceManager:
    """状态持久化管理器"""
    
    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or os.path.join(os.path.dirname(__file__), 'persistence_data')
        self.ensure_data_directory()
        
        # 数据库文件路径
        self.db_path = os.path.join(self.data_dir, 'state_persistence.db')
        self.backup_db_path = os.path.join(self.data_dir, 'state_persistence_backup.db')
        
        # JSON状态文件路径
        self.state_file = os.path.join(self.data_dir, 'current_state.json')
        self.backup_state_file = os.path.join(self.data_dir, 'backup_state.json')
        
        # 会话数据文件
        self.sessions_file = os.path.join(self.data_dir, 'monitoring_sessions.json')
        
        # 初始化数据库
        self.init_database()
        
        logging.info(f"状态持久化管理器初始化完成，数据目录: {self.data_dir}")
    
    def ensure_data_directory(self):
        """确保数据目录存在"""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir, exist_ok=True)
    
    def init_database(self):
        """初始化SQLite数据库"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 创建监控会话表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS monitoring_sessions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url_id TEXT UNIQUE NOT NULL,
                        url TEXT NOT NULL,
                        script_name TEXT NOT NULL,
                        start_time REAL NOT NULL,
                        last_activity REAL NOT NULL,
                        status TEXT DEFAULT 'active',
                        cookies TEXT,
                        local_storage TEXT,
                        session_storage TEXT,
                        page_state TEXT,
                        injection_state TEXT,
                        error_count INTEGER DEFAULT 0,
                        success_count INTEGER DEFAULT 0,
                        metadata TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 创建系统状态表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS system_states (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        browser_config TEXT NOT NULL,
                        global_settings TEXT NOT NULL,
                        performance_metrics TEXT,
                        restart_context TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 创建状态快照表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS state_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        snapshot_type TEXT NOT NULL,
                        timestamp REAL NOT NULL,
                        data TEXT NOT NULL,
                        checksum TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                conn.commit()
                
        except Exception as e:
            logging.error(f"初始化数据库失败: {e}")
    
    async def save_monitoring_session(self, session: MonitoringSession) -> bool:
        """保存监控会话"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 序列化复杂数据
                cookies_json = json.dumps(session.cookies) if session.cookies else None
                local_storage_json = json.dumps(session.local_storage) if session.local_storage else None
                session_storage_json = json.dumps(session.session_storage) if session.session_storage else None
                page_state_json = json.dumps(session.page_state) if session.page_state else None
                injection_state_json = json.dumps(session.injection_state) if session.injection_state else None
                metadata_json = json.dumps(session.metadata)
                
                # 使用REPLACE INTO实现upsert操作
                cursor.execute('''
                    REPLACE INTO monitoring_sessions (
                        url_id, url, script_name, start_time, last_activity, status,
                        cookies, local_storage, session_storage, page_state, injection_state,
                        error_count, success_count, metadata, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''', (
                    session.url_id, session.url, session.script_name,
                    session.start_time, session.last_activity, session.status,
                    cookies_json, local_storage_json, session_storage_json,
                    page_state_json, injection_state_json,
                    session.error_count, session.success_count, metadata_json
                ))
                
                conn.commit()
                return True
                
        except Exception as e:
            logging.error(f"保存监控会话失败: {e}")
            return False
    
    async def load_monitoring_session(self, url_id: str) -> Optional[MonitoringSession]:
        """加载监控会话"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT url_id, url, script_name, start_time, last_activity, status,
                           cookies, local_storage, session_storage, page_state, injection_state,
                           error_count, success_count, metadata
                    FROM monitoring_sessions WHERE url_id = ?
                ''', (url_id,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                # 反序列化数据
                cookies = json.loads(row[6]) if row[6] else None
                local_storage = json.loads(row[7]) if row[7] else None
                session_storage = json.loads(row[8]) if row[8] else None
                page_state = json.loads(row[9]) if row[9] else None
                injection_state = json.loads(row[10]) if row[10] else None
                metadata = json.loads(row[13]) if row[13] else {}
                
                return MonitoringSession(
                    url_id=row[0], url=row[1], script_name=row[2],
                    start_time=row[3], last_activity=row[4], status=row[5],
                    cookies=cookies, local_storage=local_storage,
                    session_storage=session_storage, page_state=page_state,
                    injection_state=injection_state, error_count=row[11],
                    success_count=row[12], metadata=metadata
                )
                
        except Exception as e:
            logging.error(f"加载监控会话失败: {e}")
            return None
    
    async def load_all_monitoring_sessions(self) -> List[MonitoringSession]:
        """加载所有监控会话"""
        sessions = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT url_id, url, script_name, start_time, last_activity, status,
                           cookies, local_storage, session_storage, page_state, injection_state,
                           error_count, success_count, metadata
                    FROM monitoring_sessions WHERE status = 'active'
                    ORDER BY last_activity DESC
                ''')
                
                for row in cursor.fetchall():
                    try:
                        # 反序列化数据
                        cookies = json.loads(row[6]) if row[6] else None
                        local_storage = json.loads(row[7]) if row[7] else None
                        session_storage = json.loads(row[8]) if row[8] else None
                        page_state = json.loads(row[9]) if row[9] else None
                        injection_state = json.loads(row[10]) if row[10] else None
                        metadata = json.loads(row[13]) if row[13] else {}
                        
                        session = MonitoringSession(
                            url_id=row[0], url=row[1], script_name=row[2],
                            start_time=row[3], last_activity=row[4], status=row[5],
                            cookies=cookies, local_storage=local_storage,
                            session_storage=session_storage, page_state=page_state,
                            injection_state=injection_state, error_count=row[11],
                            success_count=row[12], metadata=metadata
                        )
                        sessions.append(session)
                        
                    except Exception as e:
                        logging.error(f"解析监控会话数据失败: {e}")
                        continue
                
        except Exception as e:
            logging.error(f"加载所有监控会话失败: {e}")
        
        return sessions
    
    async def save_system_state(self, state: SystemState) -> bool:
        """保存系统状态"""
        try:
            # 保存到数据库
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO system_states (
                        timestamp, browser_config, global_settings, 
                        performance_metrics, restart_context
                    ) VALUES (?, ?, ?, ?, ?)
                ''', (
                    state.timestamp,
                    json.dumps(state.browser_config),
                    json.dumps(state.global_settings),
                    json.dumps(state.performance_metrics),
                    json.dumps(state.restart_context)
                ))
                conn.commit()
            
            # 同时保存到JSON文件作为备份
            await self._save_state_to_json(state)
            
            return True
            
        except Exception as e:
            logging.error(f"保存系统状态失败: {e}")
            return False
    
    async def _save_state_to_json(self, state: SystemState):
        """保存状态到JSON文件"""
        try:
            # 备份当前状态文件
            if os.path.exists(self.state_file):
                if os.path.exists(self.backup_state_file):
                    os.remove(self.backup_state_file)
                os.rename(self.state_file, self.backup_state_file)
            
            # 保存新状态
            state_data = {
                'timestamp': state.timestamp,
                'browser_config': state.browser_config,
                'monitoring_sessions': [asdict(session) for session in state.monitoring_sessions],
                'global_settings': state.global_settings,
                'performance_metrics': state.performance_metrics,
                'restart_context': state.restart_context
            }
            
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logging.error(f"保存状态到JSON文件失败: {e}")
    
    async def load_latest_system_state(self) -> Optional[SystemState]:
        """加载最新的系统状态"""
        try:
            # 首先尝试从数据库加载
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT timestamp, browser_config, global_settings, 
                           performance_metrics, restart_context
                    FROM system_states 
                    ORDER BY timestamp DESC LIMIT 1
                ''')
                
                row = cursor.fetchone()
                if row:
                    # 加载对应的监控会话
                    sessions = await self.load_all_monitoring_sessions()
                    
                    return SystemState(
                        timestamp=row[0],
                        browser_config=json.loads(row[1]),
                        monitoring_sessions=sessions,
                        global_settings=json.loads(row[2]),
                        performance_metrics=json.loads(row[3]) if row[3] else {},
                        restart_context=json.loads(row[4]) if row[4] else {}
                    )
            
            # 如果数据库没有数据，尝试从JSON文件加载
            return await self._load_state_from_json()
            
        except Exception as e:
            logging.error(f"加载最新系统状态失败: {e}")
            return None
    
    async def _load_state_from_json(self) -> Optional[SystemState]:
        """从JSON文件加载状态"""
        try:
            state_file_to_use = self.state_file
            if not os.path.exists(state_file_to_use) and os.path.exists(self.backup_state_file):
                state_file_to_use = self.backup_state_file
                logging.warning("使用备份状态文件")
            
            if not os.path.exists(state_file_to_use):
                return None
            
            with open(state_file_to_use, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 重建监控会话对象
            sessions = []
            for session_data in data.get('monitoring_sessions', []):
                session = MonitoringSession(**session_data)
                sessions.append(session)
            
            return SystemState(
                timestamp=data['timestamp'],
                browser_config=data['browser_config'],
                monitoring_sessions=sessions,
                global_settings=data['global_settings'],
                performance_metrics=data.get('performance_metrics', {}),
                restart_context=data.get('restart_context', {})
            )
            
        except Exception as e:
            logging.error(f"从JSON文件加载状态失败: {e}")
            return None
    
    async def create_state_snapshot(self, snapshot_type: str, data: Any) -> bool:
        """创建状态快照"""
        try:
            import hashlib
            
            # 序列化数据
            if isinstance(data, (dict, list)):
                data_str = json.dumps(data, ensure_ascii=False)
            else:
                data_str = str(data)
            
            # 计算校验和
            checksum = hashlib.md5(data_str.encode('utf-8')).hexdigest()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO state_snapshots (snapshot_type, timestamp, data, checksum)
                    VALUES (?, ?, ?, ?)
                ''', (snapshot_type, time.time(), data_str, checksum))
                conn.commit()
            
            return True
            
        except Exception as e:
            logging.error(f"创建状态快照失败: {e}")
            return False
    
    async def get_state_snapshots(self, snapshot_type: str = None, limit: int = 10) -> List[Dict]:
        """获取状态快照"""
        snapshots = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                if snapshot_type:
                    cursor.execute('''
                        SELECT id, snapshot_type, timestamp, data, checksum, created_at
                        FROM state_snapshots 
                        WHERE snapshot_type = ?
                        ORDER BY timestamp DESC LIMIT ?
                    ''', (snapshot_type, limit))
                else:
                    cursor.execute('''
                        SELECT id, snapshot_type, timestamp, data, checksum, created_at
                        FROM state_snapshots 
                        ORDER BY timestamp DESC LIMIT ?
                    ''', (limit,))
                
                for row in cursor.fetchall():
                    try:
                        data = json.loads(row[3])
                    except:
                        data = row[3]  # 如果不是JSON，保持原始字符串
                    
                    snapshots.append({
                        'id': row[0],
                        'snapshot_type': row[1],
                        'timestamp': row[2],
                        'data': data,
                        'checksum': row[4],
                        'created_at': row[5]
                    })
                
        except Exception as e:
            logging.error(f"获取状态快照失败: {e}")
        
        return snapshots
    
    async def cleanup_old_data(self, days_to_keep: int = 7):
        """清理旧数据"""
        try:
            cutoff_time = time.time() - (days_to_keep * 24 * 3600)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 清理旧的系统状态
                cursor.execute('DELETE FROM system_states WHERE timestamp < ?', (cutoff_time,))
                
                # 清理旧的状态快照
                cursor.execute('DELETE FROM state_snapshots WHERE timestamp < ?', (cutoff_time,))
                
                # 清理非活跃的监控会话
                cursor.execute('''
                    DELETE FROM monitoring_sessions 
                    WHERE status != 'active' AND last_activity < ?
                ''', (cutoff_time,))
                
                conn.commit()
                
                # 获取清理统计
                cursor.execute('SELECT changes()')
                changes = cursor.fetchone()[0]
                
            logging.info(f"数据清理完成，删除了 {changes} 条记录")
            
        except Exception as e:
            logging.error(f"清理旧数据失败: {e}")
    
    async def backup_database(self) -> bool:
        """备份数据库"""
        try:
            import shutil
            
            if os.path.exists(self.backup_db_path):
                os.remove(self.backup_db_path)
            
            shutil.copy2(self.db_path, self.backup_db_path)
            logging.info("数据库备份完成")
            return True
            
        except Exception as e:
            logging.error(f"数据库备份失败: {e}")
            return False
    
    async def restore_database(self) -> bool:
        """从备份恢复数据库"""
        try:
            import shutil
            
            if not os.path.exists(self.backup_db_path):
                logging.error("备份数据库不存在")
                return False
            
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            
            shutil.copy2(self.backup_db_path, self.db_path)
            logging.info("数据库恢复完成")
            return True
            
        except Exception as e:
            logging.error(f"数据库恢复失败: {e}")
            return False
    
    def get_storage_stats(self) -> Dict:
        """获取存储统计信息"""
        stats = {
            'data_directory': self.data_dir,
            'database_size': 0,
            'backup_database_size': 0,
            'json_files_size': 0,
            'total_sessions': 0,
            'active_sessions': 0,
            'total_snapshots': 0
        }
        
        try:
            # 数据库大小
            if os.path.exists(self.db_path):
                stats['database_size'] = os.path.getsize(self.db_path)
            
            if os.path.exists(self.backup_db_path):
                stats['backup_database_size'] = os.path.getsize(self.backup_db_path)
            
            # JSON文件大小
            for file_path in [self.state_file, self.backup_state_file, self.sessions_file]:
                if os.path.exists(file_path):
                    stats['json_files_size'] += os.path.getsize(file_path)
            
            # 数据库统计
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('SELECT COUNT(*) FROM monitoring_sessions')
                stats['total_sessions'] = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM monitoring_sessions WHERE status = "active"')
                stats['active_sessions'] = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM state_snapshots')
                stats['total_snapshots'] = cursor.fetchone()[0]
            
        except Exception as e:
            logging.error(f"获取存储统计失败: {e}")
        
        return stats