"""数据库操作封装工具类

提供统一的数据库操作接口，封装常见的CRUD操作，
减少重复代码并提供更好的错误处理和日志记录。
"""

import sqlite3
import logging
import traceback
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional, Union, Tuple
from contextlib import contextmanager
from utils.db import SQLiteDB

# 获取日志记录器
logger = logging.getLogger(__name__)


class DatabaseUtils:
    """数据库操作工具类"""
    
    # 数据库实例缓存
    _db_instances = {}
    _db_lock = threading.Lock()
    
    @classmethod
    def get_db_instance(cls, db_path: str) -> SQLiteDB:
        """获取数据库实例（单例模式）
        
        Args:
            db_path: 数据库文件路径
            
        Returns:
            SQLiteDB: 数据库实例
        """
        with cls._db_lock:
            if db_path not in cls._db_instances:
                cls._db_instances[db_path] = SQLiteDB(db_path)
                logger.info(f"创建数据库实例: {db_path}")
            return cls._db_instances[db_path]
    
    @classmethod
    def create_tables(cls, db_path: str, table_schemas: Dict[str, str]) -> bool:
        """批量创建数据表
        
        Args:
            db_path: 数据库文件路径
            table_schemas: 表结构字典 {table_name: create_sql}
            
        Returns:
            bool: 是否成功创建所有表
        """
        try:
            db = cls.get_db_instance(db_path)
            
            for table_name, create_sql in table_schemas.items():
                try:
                    db.execute(create_sql)
                    logger.debug(f"创建数据表: {table_name}")
                except Exception as e:
                    logger.error(f"创建数据表 {table_name} 失败: {e}")
                    return False
            
            logger.info("数据库表创建完成")
            return True
            
        except Exception as e:
            logger.error(f"数据库表创建失败: {e}")
            logger.error(traceback.format_exc())
            return False
    
    @classmethod
    def insert_data(cls, db_path: str, table_name: str, data: Dict[str, Any], 
                   ignore_errors: bool = False) -> bool:
        """插入数据到指定表
        
        Args:
            db_path: 数据库文件路径
            table_name: 表名
            data: 要插入的数据字典
            ignore_errors: 是否忽略错误
            
        Returns:
            bool: 是否插入成功
        """
        try:
            if not data:
                logger.warning("插入数据为空")
                return False
            
            db = cls.get_db_instance(db_path)
            
            # 构建插入SQL
            columns = list(data.keys())
            placeholders = ['?' for _ in columns]
            values = list(data.values())
            
            sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
            
            db.execute(sql, values)
            logger.debug(f"插入数据到表 {table_name}: {data}")
            return True
            
        except Exception as e:
            if ignore_errors:
                logger.warning(f"插入数据失败（已忽略）: {e}")
                return False
            else:
                logger.error(f"插入数据到表 {table_name} 失败: {e}")
                logger.error(traceback.format_exc())
                return False
    
    @classmethod
    def update_data(cls, db_path: str, table_name: str, data: Dict[str, Any], 
                   where_condition: str, where_params: Tuple = ()) -> bool:
        """更新表中的数据
        
        Args:
            db_path: 数据库文件路径
            table_name: 表名
            data: 要更新的数据字典
            where_condition: WHERE条件
            where_params: WHERE条件的参数
            
        Returns:
            bool: 是否更新成功
        """
        try:
            if not data:
                logger.warning("更新数据为空")
                return False
            
            db = cls.get_db_instance(db_path)
            
            # 构建更新SQL
            set_clauses = [f"{key} = ?" for key in data.keys()]
            values = list(data.values())
            values.extend(where_params)
            
            sql = f"UPDATE {table_name} SET {', '.join(set_clauses)} WHERE {where_condition}"
            
            db.execute(sql, values)
            logger.debug(f"更新表 {table_name} 数据: {data}")
            return True
            
        except Exception as e:
            logger.error(f"更新表 {table_name} 数据失败: {e}")
            logger.error(traceback.format_exc())
            return False
    
    @classmethod
    def query_data(cls, db_path: str, sql: str, params: Tuple = ()) -> List[Tuple]:
        """查询数据
        
        Args:
            db_path: 数据库文件路径
            sql: 查询SQL
            params: SQL参数
            
        Returns:
            List[Tuple]: 查询结果列表
        """
        try:
            db = cls.get_db_instance(db_path)
            result = db.fetch_all(sql, params)
            logger.debug(f"查询数据: {sql}, 结果条数: {len(result) if result else 0}")
            return result or []
            
        except Exception as e:
            logger.error(f"查询数据失败: {e}")
            logger.error(traceback.format_exc())
            return []
    
    @classmethod
    def query_one(cls, db_path: str, sql: str, params: Tuple = ()) -> Optional[Tuple]:
        """查询单条数据
        
        Args:
            db_path: 数据库文件路径
            sql: 查询SQL
            params: SQL参数
            
        Returns:
            Optional[Tuple]: 查询结果，如果没有结果返回None
        """
        try:
            result = cls.query_data(db_path, sql, params)
            return result[0] if result else None
            
        except Exception as e:
            logger.error(f"查询单条数据失败: {e}")
            return None
    
    @classmethod
    def delete_data(cls, db_path: str, table_name: str, where_condition: str, 
                   where_params: Tuple = ()) -> bool:
        """删除表中的数据
        
        Args:
            db_path: 数据库文件路径
            table_name: 表名
            where_condition: WHERE条件
            where_params: WHERE条件的参数
            
        Returns:
            bool: 是否删除成功
        """
        try:
            db = cls.get_db_instance(db_path)
            
            sql = f"DELETE FROM {table_name} WHERE {where_condition}"
            db.execute(sql, where_params)
            logger.debug(f"删除表 {table_name} 数据: {where_condition}")
            return True
            
        except Exception as e:
            logger.error(f"删除表 {table_name} 数据失败: {e}")
            logger.error(traceback.format_exc())
            return False
    
    @classmethod
    def count_records(cls, db_path: str, table_name: str, where_condition: str = "", 
                     where_params: Tuple = ()) -> int:
        """统计表中记录数
        
        Args:
            db_path: 数据库文件路径
            table_name: 表名
            where_condition: WHERE条件（可选）
            where_params: WHERE条件的参数
            
        Returns:
            int: 记录数量
        """
        try:
            sql = f"SELECT COUNT(*) FROM {table_name}"
            if where_condition:
                sql += f" WHERE {where_condition}"
            
            result = cls.query_one(db_path, sql, where_params)
            return result[0] if result else 0
            
        except Exception as e:
            logger.error(f"统计表 {table_name} 记录数失败: {e}")
            return 0
    
    @classmethod
    def table_exists(cls, db_path: str, table_name: str) -> bool:
        """检查表是否存在
        
        Args:
            db_path: 数据库文件路径
            table_name: 表名
            
        Returns:
            bool: 表是否存在
        """
        try:
            sql = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
            result = cls.query_one(db_path, sql, (table_name,))
            return result is not None
            
        except Exception as e:
            logger.error(f"检查表 {table_name} 是否存在失败: {e}")
            return False


class CommentDataHandler:
    """弹幕数据处理器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.table_name = "danmu"
        self._ensure_table_exists()
    
    def _ensure_table_exists(self):
        """确保弹幕表存在"""
        schema = {
            self.table_name: '''
            CREATE TABLE IF NOT EXISTS danmu (
                username TEXT NOT NULL,
                content TEXT NOT NULL,
                ts DATETIME NOT NULL
            )
            '''
        }
        DatabaseUtils.create_tables(self.db_path, schema)
    
    def insert_comment(self, username: str, content: str, timestamp: datetime = None) -> bool:
        """插入弹幕记录
        
        Args:
            username: 用户名
            content: 弹幕内容
            timestamp: 时间戳，默认为当前时间
            
        Returns:
            bool: 是否插入成功
        """
        data = {
            "username": username,
            "content": content,
            "ts": timestamp or datetime.now()
        }
        return DatabaseUtils.insert_data(self.db_path, self.table_name, data)
    
    def get_recent_comments(self, limit: int = 100) -> List[Tuple]:
        """获取最近的弹幕记录
        
        Args:
            limit: 返回记录数限制
            
        Returns:
            List[Tuple]: 弹幕记录列表
        """
        sql = f"SELECT * FROM {self.table_name} ORDER BY ts DESC LIMIT ?"
        return DatabaseUtils.query_data(self.db_path, sql, (limit,))
    
    def get_user_comment_count(self, username: str) -> int:
        """获取用户弹幕数量
        
        Args:
            username: 用户名
            
        Returns:
            int: 弹幕数量
        """
        return DatabaseUtils.count_records(self.db_path, self.table_name, "username = ?", (username,))


class GiftDataHandler:
    """礼物数据处理器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.table_name = "gift"
        self._ensure_table_exists()
    
    def _ensure_table_exists(self):
        """确保礼物表存在"""
        schema = {
            self.table_name: '''
            CREATE TABLE IF NOT EXISTS gift (
                username TEXT NOT NULL,
                gift_name TEXT NOT NULL,
                gift_num INT NOT NULL,
                unit_price REAL NOT NULL,
                total_price REAL NOT NULL,
                ts DATETIME NOT NULL
            )
            '''
        }
        DatabaseUtils.create_tables(self.db_path, schema)
    
    def insert_gift(self, username: str, gift_name: str, gift_num: int, 
                   unit_price: float, total_price: float, timestamp: datetime = None) -> bool:
        """插入礼物记录
        
        Args:
            username: 用户名
            gift_name: 礼物名称
            gift_num: 礼物数量
            unit_price: 单价
            total_price: 总价
            timestamp: 时间戳，默认为当前时间
            
        Returns:
            bool: 是否插入成功
        """
        data = {
            "username": username,
            "gift_name": gift_name,
            "gift_num": gift_num,
            "unit_price": unit_price,
            "total_price": total_price,
            "ts": timestamp or datetime.now()
        }
        return DatabaseUtils.insert_data(self.db_path, self.table_name, data)
    
    def get_top_gifts(self, limit: int = 10) -> List[Tuple]:
        """获取礼物排行榜
        
        Args:
            limit: 返回记录数限制
            
        Returns:
            List[Tuple]: 礼物记录列表
        """
        sql = f"SELECT * FROM {self.table_name} ORDER BY total_price DESC LIMIT ?"
        return DatabaseUtils.query_data(self.db_path, sql, (limit,))
    
    def get_user_total_gift_value(self, username: str) -> float:
        """获取用户礼物总价值
        
        Args:
            username: 用户名
            
        Returns:
            float: 礼物总价值
        """
        sql = f"SELECT SUM(total_price) FROM {self.table_name} WHERE username = ?"
        result = DatabaseUtils.query_one(self.db_path, sql, (username,))
        return result[0] if result and result[0] else 0.0


class IntegralDataHandler:
    """积分数据处理器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.table_name = "integral"
        self._ensure_table_exists()
    
    def _ensure_table_exists(self):
        """确保积分表存在"""
        schema = {
            self.table_name: '''
            CREATE TABLE IF NOT EXISTS integral (
                platform TEXT NOT NULL,
                username TEXT NOT NULL,
                uid TEXT NOT NULL,
                integral INT NOT NULL,
                view_num INT NOT NULL,
                sign_num INT NOT NULL,
                last_sign_ts DATETIME NOT NULL,
                total_price INT NOT NULL,
                last_ts DATETIME NOT NULL
            )
            '''
        }
        DatabaseUtils.create_tables(self.db_path, schema)
    
    def get_user_integral(self, username: str) -> Optional[Tuple]:
        """获取用户积分信息
        
        Args:
            username: 用户名
            
        Returns:
            Optional[Tuple]: 用户积分记录，如果不存在返回None
        """
        sql = f"SELECT * FROM {self.table_name} WHERE username = ?"
        return DatabaseUtils.query_one(self.db_path, sql, (username,))
    
    def insert_user_integral(self, platform: str, username: str, uid: str, 
                           integral: int, view_num: int = 1, sign_num: int = 0, 
                           last_sign_ts: datetime = None, total_price: int = 0, 
                           last_ts: datetime = None) -> bool:
        """插入用户积分记录
        
        Args:
            platform: 平台
            username: 用户名
            uid: 用户ID
            integral: 积分
            view_num: 观看次数
            sign_num: 签到次数
            last_sign_ts: 最后签到时间
            total_price: 总消费
            last_ts: 最后活动时间
            
        Returns:
            bool: 是否插入成功
        """
        data = {
            "platform": platform,
            "username": username,
            "uid": uid,
            "integral": integral,
            "view_num": view_num,
            "sign_num": sign_num,
            "last_sign_ts": last_sign_ts or datetime.now(),
            "total_price": total_price,
            "last_ts": last_ts or datetime.now()
        }
        return DatabaseUtils.insert_data(self.db_path, self.table_name, data)
    
    def update_user_integral(self, username: str, **updates) -> bool:
        """更新用户积分信息
        
        Args:
            username: 用户名
            **updates: 要更新的字段
            
        Returns:
            bool: 是否更新成功
        """
        if not updates:
            return False
        
        return DatabaseUtils.update_data(
            self.db_path, self.table_name, updates, "username = ?", (username,)
        )
    
    def get_integral_ranking(self, order_by: str = "integral", limit: int = 10) -> List[Tuple]:
        """获取积分排行榜
        
        Args:
            order_by: 排序字段（integral/view_num/sign_num/total_price）
            limit: 返回记录数限制
            
        Returns:
            List[Tuple]: 积分排行榜
        """
        sql = f"SELECT * FROM {self.table_name} ORDER BY {order_by} DESC LIMIT ?"
        return DatabaseUtils.query_data(self.db_path, sql, (limit,))


class EntranceDataHandler:
    """入场数据处理器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.table_name = "entrance"
        self._ensure_table_exists()
    
    def _ensure_table_exists(self):
        """确保入场表存在"""
        schema = {
            self.table_name: '''
            CREATE TABLE IF NOT EXISTS entrance (
                username TEXT NOT NULL,
                ts DATETIME NOT NULL
            )
            '''
        }
        DatabaseUtils.create_tables(self.db_path, schema)
    
    def insert_entrance(self, username: str, timestamp: datetime = None) -> bool:
        """插入入场记录
        
        Args:
            username: 用户名
            timestamp: 时间戳，默认为当前时间
            
        Returns:
            bool: 是否插入成功
        """
        data = {
            "username": username,
            "ts": timestamp or datetime.now()
        }
        return DatabaseUtils.insert_data(self.db_path, self.table_name, data)
    
    def get_recent_entrances(self, limit: int = 100) -> List[Tuple]:
        """获取最近的入场记录
        
        Args:
            limit: 返回记录数限制
            
        Returns:
            List[Tuple]: 入场记录列表
        """
        sql = f"SELECT * FROM {self.table_name} ORDER BY ts DESC LIMIT ?"
        return DatabaseUtils.query_data(self.db_path, sql, (limit,))


# 工厂函数，用于创建数据处理器
def create_comment_handler(db_path: str) -> CommentDataHandler:
    """创建弹幕数据处理器"""
    return CommentDataHandler(db_path)

def create_gift_handler(db_path: str) -> GiftDataHandler:
    """创建礼物数据处理器"""
    return GiftDataHandler(db_path)

def create_integral_handler(db_path: str) -> IntegralDataHandler:
    """创建积分数据处理器"""
    return IntegralDataHandler(db_path)

def create_entrance_handler(db_path: str) -> EntranceDataHandler:
    """创建入场数据处理器"""
    return EntranceDataHandler(db_path)