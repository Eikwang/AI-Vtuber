"""消息数据标准化工具类

提供统一的消息数据结构标准化功能，确保不同来源的消息数据
都能转换为标准格式，便于后续处理。
"""

import time
import logging
from typing import Dict, Any, Optional, Union
from copy import deepcopy

# 获取日志记录器
logger = logging.getLogger(__name__)


class MessageUtils:
    """消息数据标准化工具类"""
    
    # 标准消息字段定义
    STANDARD_MESSAGE_FIELDS = {
        # 必需字段
        "type": str,           # 消息类型
        "content": str,        # 消息内容
        "username": str,       # 用户名
        "platform": str,       # 平台
        "timestamp": float,    # 时间戳
        
        # 可选字段
        "user_face": str,      # 用户头像
        "user_id": str,        # 用户ID
        "priority": int,       # 优先级
        "tts_type": str,       # TTS类型
        "data": dict,          # TTS配置数据
        "config": dict,        # 过滤配置
        
        # 扩展字段（用于特殊消息类型）
        "gift_name": str,      # 礼物名称
        "gift_info": dict,     # 礼物信息
        "num": int,            # 数量
        "unit_price": float,   # 单价
        "total_price": float,  # 总价
        "file_path": str,      # 文件路径
        "insert_index": int,   # 插入索引
        
        # 内部标记字段
        "_use_assistant_anchor_tts": bool,  # 是否使用助播TTS
        "_use_metahuman_stream": bool,      # 是否使用metahuman_stream
        "fragment_index": int,              # 片段索引
        "total_fragments": int,             # 总片段数
        "original_content": str,            # 原始内容
        "content_type": str,                # 内容类型
    }
    
    # 消息类型映射
    MESSAGE_TYPE_MAPPING = {
        # 弹幕相关
        "comment": "comment",
        "弹幕": "comment",
        "chat": "comment",
        "danmaku": "comment",
        
        # 礼物相关
        "gift": "gift",
        "礼物": "gift",
        "present": "gift",
        
        # 用户行为
        "entrance": "entrance",
        "进入": "entrance",
        "enter": "entrance",
        "follow": "follow",
        "关注": "follow",
        "like": "like",
        "点赞": "like",
        
        # 系统消息
        "super_chat": "super_chat",
        "sc": "super_chat",
        "guard": "guard",
        "舰长": "guard",
        
        # 其他类型
        "talk": "talk",
        "local_qa_audio": "local_qa_audio",
        "song": "song",
        "reread": "reread",
        "key_mapping": "key_mapping",
        "integral": "integral",
        "read_comment": "read_comment",
        "schedule": "schedule",
        "idle_time_task": "idle_time_task",
        "abnormal_alarm": "abnormal_alarm",
        "image_recognition_schedule": "image_recognition_schedule",
        "trends_copywriting": "trends_copywriting",
        "assistant_anchor_text": "assistant_anchor_text",
        "assistant_anchor_audio": "assistant_anchor_audio",
        "copywriting": "copywriting",
        "copywriting2": "copywriting2",
        "copywriting3": "copywriting3",
        "copywriting4": "copywriting4",
    }
    
    # 平台名称标准化映射
    PLATFORM_MAPPING = {
        "bilibili": "bilibili",
        "哔哩哔哩": "bilibili",
        "b站": "bilibili",
        "抖音": "douyin",
        "douyin": "douyin",
        "dy": "douyin",
        "快手": "kuaishou",
        "kuaishou": "kuaishou",
        "ks": "kuaishou",
        "tiktok": "tiktok",
        "twitch": "twitch",
        "youtube": "youtube",
        "微信": "weixin",
        "weixin": "weixin",
        "wx": "weixin",
        "让弹幕飞": "barrage_fly",
        "barrage_fly": "barrage_fly",
        "ordinaryroad": "barrage_fly",
        "local": "local",
        "本地": "local",
    }
    
    @classmethod
    def normalize_message(cls, raw_data: Union[Dict[str, Any], str], message_type: Optional[str] = None) -> Dict[str, Any]:
        """标准化消息数据
        
        Args:
            raw_data: 原始数据（字典或字符串）
            message_type: 强制指定的消息类型
            
        Returns:
            dict: 标准化的消息数据
        """
        try:
            # 基础数据检查
            if not raw_data:
                logger.warning("收到空的消息数据")
                return cls._create_empty_message()
            
            # 字符串数据处理
            if isinstance(raw_data, str):
                return cls._normalize_string_message(raw_data, message_type)
            
            # 字典数据处理
            if isinstance(raw_data, dict):
                return cls._normalize_dict_message(raw_data, message_type)
            
            logger.warning(f"不支持的消息数据类型: {type(raw_data)}")
            return cls._create_empty_message()
            
        except Exception as e:
            logger.error(f"消息数据标准化失败: {e}")
            return cls._create_empty_message()
    
    @classmethod
    def _normalize_dict_message(cls, data: Dict[str, Any], force_type: Optional[str] = None) -> Dict[str, Any]:
        """标准化字典格式的消息数据"""
        try:
            # 创建标准化后的消息
            normalized = {
                "type": cls._normalize_message_type(force_type or data.get("type", "comment")),
                "content": cls._extract_content(data),
                "username": cls._extract_username(data),
                "platform": cls._normalize_platform(data.get("platform", "unknown")),
                "timestamp": data.get("timestamp", time.time()),
                "priority": cls._extract_priority(data),
            }
            
            # 添加可选字段
            optional_fields = [
                "user_face", "user_id", "tts_type", "data", "config",
                "gift_name", "gift_info", "num", "unit_price", "total_price",
                "file_path", "insert_index", "_use_assistant_anchor_tts",
                "_use_metahuman_stream", "fragment_index", "total_fragments",
                "original_content", "content_type"
            ]
            
            for field in optional_fields:
                if field in data and data[field] is not None:
                    normalized[field] = data[field]
            
            # 特殊字段处理
            cls._handle_special_fields(normalized, data)
            
            return normalized
            
        except Exception as e:
            logger.error(f"字典消息标准化失败: {e}")
            return cls._create_empty_message()
    
    @classmethod
    def _normalize_string_message(cls, content: str, message_type: Optional[str] = None) -> Dict[str, Any]:
        """标准化字符串格式的消息数据"""
        return {
            "type": cls._normalize_message_type(message_type or "comment"),
            "content": content.strip(),
            "username": "system",
            "platform": "local",
            "timestamp": time.time(),
            "priority": 5,
        }
    
    @classmethod
    def _extract_content(cls, data: Dict[str, Any]) -> str:
        """提取消息内容"""
        # 尝试多个可能的内容字段
        content_fields = ["content", "message", "text", "msg", "body"]
        for field in content_fields:
            if field in data and data[field]:
                return str(data[field]).strip()
        
        # 特殊情况处理
        if data.get("type") == "entrance":
            return "进入直播间"
        elif data.get("type") == "follow":
            return "关注了主播"
        elif data.get("type") == "like":
            return f"点赞了 {data.get('num', 1)} 次"
        elif data.get("type") == "gift":
            gift_name = data.get("gift_name", "礼物")
            num = data.get("num", 1)
            return f"赠送了 {num} 个{gift_name}"
        
        return ""
    
    @classmethod
    def _extract_username(cls, data: Dict[str, Any]) -> str:
        """提取用户名"""
        # 尝试多个可能的用户名字段
        username_fields = ["username", "user_name", "uname", "name", "nick_name", "nickname"]
        for field in username_fields:
            if field in data and data[field]:
                return str(data[field]).strip()
        
        return "unknown"
    
    @classmethod
    def _extract_priority(cls, data: Dict[str, Any]) -> int:
        """提取或计算优先级"""
        # 如果已有优先级，直接返回
        if "priority" in data and isinstance(data["priority"], (int, float)):
            try:
                return int(data["priority"])
            except (ValueError, TypeError):
                pass
        
        # 根据消息类型设置默认优先级
        message_type = data.get("type", "comment")
        priority_mapping = {
            "reread_top_priority": 10,
            "talk": 9,
            "comment": 8,
            "local_qa_audio": 7,
            "song": 6,
            "reread": 5,
            "key_mapping": 4,
            "integral": 3,
            "read_comment": 2,
            "gift": 2,
            "entrance": 1,
            "follow": 1,
            "schedule": 0,
            "idle_time_task": 0,
            "abnormal_alarm": 10,
        }
        
        return priority_mapping.get(message_type, 5)
    
    @classmethod
    def _normalize_message_type(cls, message_type: str) -> str:
        """标准化消息类型"""
        if not message_type:
            return "comment"
        
        message_type = str(message_type).lower().strip()
        return cls.MESSAGE_TYPE_MAPPING.get(message_type, message_type)
    
    @classmethod
    def _normalize_platform(cls, platform: str) -> str:
        """标准化平台名称"""
        if not platform:
            return "unknown"
        
        platform = str(platform).lower().strip()
        return cls.PLATFORM_MAPPING.get(platform, platform)
    
    @classmethod
    def _handle_special_fields(cls, normalized: Dict[str, Any], original: Dict[str, Any]):
        """处理特殊字段"""
        try:
            # 礼物信息整合
            if normalized["type"] == "gift":
                gift_info = {
                    "name": original.get("gift_name", ""),
                    "num": original.get("num", 1),
                    "unit_price": original.get("unit_price", 0),
                    "total_price": original.get("total_price", 0),
                }
                normalized["gift_info"] = gift_info
            
            # TTS配置处理
            if "tts_type" not in normalized and "data" in original:
                tts_data = original.get("data", {})
                if isinstance(tts_data, dict):
                    normalized["data"] = tts_data
            
            # 文件路径统一
            file_fields = ["file_path", "voice_path", "audio_path", "path"]
            for field in file_fields:
                if field in original and original[field]:
                    normalized["file_path"] = original[field]
                    break
            
        except Exception as e:
            logger.warning(f"处理特殊字段时出错: {e}")
    
    @classmethod
    def _create_empty_message(cls) -> Dict[str, Any]:
        """创建空消息"""
        return {
            "type": "comment",
            "content": "",
            "username": "system",
            "platform": "unknown",
            "timestamp": time.time(),
            "priority": 5,
        }
    
    @classmethod
    def validate_message(cls, message: Dict[str, Any]) -> bool:
        """验证消息数据是否符合标准格式
        
        Args:
            message: 待验证的消息数据
            
        Returns:
            bool: 是否符合标准格式
        """
        try:
            if not isinstance(message, dict):
                return False
            
            # 检查必需字段
            required_fields = ["type", "content", "username", "platform", "timestamp"]
            for field in required_fields:
                if field not in message:
                    logger.warning(f"消息缺少必需字段: {field}")
                    return False
            
            # 检查字段类型
            if not isinstance(message["type"], str):
                logger.warning("消息类型字段类型错误")
                return False
            
            if not isinstance(message["content"], str):
                logger.warning("消息内容字段类型错误")
                return False
            
            if not isinstance(message["username"], str):
                logger.warning("用户名字段类型错误")
                return False
            
            if not isinstance(message["platform"], str):
                logger.warning("平台字段类型错误")
                return False
            
            if not isinstance(message["timestamp"], (int, float)):
                logger.warning("时间戳字段类型错误")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"消息验证失败: {e}")
            return False
    
    @classmethod
    def create_audio_message(cls, message_type: str, content: str, username: str = "system",
                           platform: str = "local", tts_type: str = "edge-tts",
                           tts_data: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """创建标准的音频合成消息
        
        Args:
            message_type: 消息类型
            content: 消息内容
            username: 用户名
            platform: 平台
            tts_type: TTS类型
            tts_data: TTS配置数据
            **kwargs: 其他字段
            
        Returns:
            dict: 标准化的音频消息
        """
        try:
            message = {
                "type": cls._normalize_message_type(message_type),
                "content": content,
                "username": username,
                "platform": cls._normalize_platform(platform),
                "timestamp": time.time(),
                "tts_type": tts_type,
                "data": tts_data or {},
                "priority": cls._extract_priority(kwargs),
            }
            
            # 添加其他字段
            for key, value in kwargs.items():
                if key in cls.STANDARD_MESSAGE_FIELDS and value is not None:
                    message[key] = value
            
            return message
            
        except Exception as e:
            logger.error(f"创建音频消息失败: {e}")
            return cls._create_empty_message()
    
    @classmethod
    def copy_message_with_updates(cls, original: Dict[str, Any], **updates) -> Dict[str, Any]:
        """复制消息并更新指定字段
        
        Args:
            original: 原始消息
            **updates: 要更新的字段
            
        Returns:
            dict: 更新后的消息副本
        """
        try:
            message_copy = deepcopy(original)
            message_copy.update(updates)
            return message_copy
        except Exception as e:
            logger.error(f"复制消息失败: {e}")
            return original
    
    @classmethod
    def merge_messages(cls, *messages: Dict[str, Any]) -> Dict[str, Any]:
        """合并多个消息（后面的消息字段覆盖前面的）
        
        Args:
            *messages: 要合并的消息列表
            
        Returns:
            dict: 合并后的消息
        """
        try:
            if not messages:
                return cls._create_empty_message()
            
            merged = deepcopy(messages[0])
            for message in messages[1:]:
                if isinstance(message, dict):
                    merged.update(message)
            
            return merged
            
        except Exception as e:
            logger.error(f"合并消息失败: {e}")
            return cls._create_empty_message()