"""TTS配置统一获取工具类

提供统一的TTS配置获取接口，支持全局配置、助播配置、文案配置等
多种配置模式的统一管理和获取。
"""

import logging
from typing import Dict, Any, Tuple, Optional, Union
from copy import deepcopy

# 获取日志记录器
logger = logging.getLogger(__name__)


class TTSConfigUtils:
    """TTS配置工具类"""
    
    # 默认TTS类型
    DEFAULT_TTS_TYPE = "edge-tts"
    
    # 支持的TTS类型列表
    SUPPORTED_TTS_TYPES = [
        "edge-tts", "azure_tts", "openai_tts", "vits", "bert_vits2", 
        "vits_fast", "gpt_sovits", "gradio_tts", "cosyvoice", 
        "f5_tts", "multitts", "melotts", "index_tts", "none"
    ]
    
    @classmethod
    def get_global_tts_config(cls, config) -> Tuple[str, Dict[str, Any]]:
        """获取全局TTS配置
        
        Args:
            config: 配置对象
            
        Returns:
            Tuple[str, Dict[str, Any]]: (tts_type, tts_config)
        """
        try:
            # 获取全局TTS类型
            tts_type = config.get("audio_synthesis_type")
            
            # 验证TTS类型
            if not isinstance(tts_type, str) or tts_type not in cls.SUPPORTED_TTS_TYPES:
                logger.warning(f"全局TTS类型配置无效: {tts_type}，使用默认值: {cls.DEFAULT_TTS_TYPE}")
                tts_type = cls.DEFAULT_TTS_TYPE
            
            # 获取TTS配置
            tts_config = config.get(tts_type)
            if not isinstance(tts_config, dict):
                logger.warning(f"全局TTS配置无效: {tts_type}，使用空配置")
                tts_config = {}
            
            logger.debug(f"获取全局TTS配置: {tts_type}")
            return tts_type, deepcopy(tts_config)
            
        except Exception as e:
            logger.error(f"获取全局TTS配置失败: {e}")
            return cls.DEFAULT_TTS_TYPE, {}
    
    @classmethod
    def get_assistant_tts_config(cls, config) -> Tuple[str, Dict[str, Any]]:
        """获取助播TTS配置
        
        Args:
            config: 配置对象
            
        Returns:
            Tuple[str, Dict[str, Any]]: (tts_type, tts_config)
        """
        try:
            # 获取助播配置
            assistant_config = config.get("assistant_anchor", {})
            if not isinstance(assistant_config, dict) or not assistant_config.get("enable", False):
                logger.debug("助播功能未启用，回退到全局TTS配置")
                return cls.get_global_tts_config(config)
            
            # 获取助播TTS类型
            tts_type = assistant_config.get("audio_synthesis_type")
            if not isinstance(tts_type, str) or tts_type not in cls.SUPPORTED_TTS_TYPES:
                logger.warning(f"助播TTS类型配置无效: {tts_type}，回退到全局配置")
                return cls.get_global_tts_config(config)
            
            # 获取基础TTS配置（从根级别获取）
            base_tts_config = config.get(tts_type, {})
            if not isinstance(base_tts_config, dict):
                base_tts_config = {}
            
            # 获取助播覆盖配置
            assistant_override_config = assistant_config.get("audio_synthesis_config", {}).get(tts_type, {})
            if not isinstance(assistant_override_config, dict):
                assistant_override_config = {}
            
            # 深度合并配置（助播覆盖优先）
            final_tts_config = cls._deep_merge_configs(base_tts_config, assistant_override_config)
            
            # 特殊处理gpt_sovits的type字段
            if tts_type == "gpt_sovits" and "type" not in final_tts_config:
                final_tts_config = cls._infer_gpt_sovits_type(final_tts_config)
            
            logger.debug(f"获取助播TTS配置: {tts_type}")
            return tts_type, final_tts_config
            
        except Exception as e:
            logger.error(f"获取助播TTS配置失败: {e}")
            return cls.get_global_tts_config(config)
    
    @classmethod
    def get_copywriting_tts_config(cls, config) -> Tuple[str, Dict[str, Any]]:
        """获取文案TTS配置
        
        Args:
            config: 配置对象
            
        Returns:
            Tuple[str, Dict[str, Any]]: (tts_type, tts_config)
        """
        try:
            # 获取文案配置
            copywriting_config = config.get("copywriting", {})
            audio_synthesis_config = copywriting_config.get("audio_synthesis", {})
            
            if not isinstance(audio_synthesis_config, dict):
                logger.debug("文案TTS配置不存在，回退到全局TTS配置")
                return cls.get_global_tts_config(config)
            
            # 获取文案TTS类型
            tts_type = audio_synthesis_config.get("type")
            if not isinstance(tts_type, str) or tts_type not in cls.SUPPORTED_TTS_TYPES:
                logger.warning(f"文案TTS类型配置无效: {tts_type}，回退到全局配置")
                return cls.get_global_tts_config(config)
            
            # 获取TTS配置
            tts_config = audio_synthesis_config.get(tts_type, {})
            if not isinstance(tts_config, dict):
                tts_config = {}
            
            logger.debug(f"获取文案TTS配置: {tts_type}")
            return tts_type, deepcopy(tts_config)
            
        except Exception as e:
            logger.error(f"获取文案TTS配置失败: {e}")
            return cls.get_global_tts_config(config)
    
    @classmethod
    def get_tts_config_by_type(cls, config, config_type: str = "global") -> Tuple[str, Dict[str, Any]]:
        """根据类型获取TTS配置
        
        Args:
            config: 配置对象
            config_type: 配置类型 ("global", "assistant", "copywriting")
            
        Returns:
            Tuple[str, Dict[str, Any]]: (tts_type, tts_config)
        """
        try:
            if config_type == "assistant":
                return cls.get_assistant_tts_config(config)
            elif config_type == "copywriting":
                return cls.get_copywriting_tts_config(config)
            else:
                return cls.get_global_tts_config(config)
                
        except Exception as e:
            logger.error(f"获取TTS配置失败，类型: {config_type}, 错误: {e}")
            return cls.get_global_tts_config(config)
    
    @classmethod
    def should_use_assistant_tts(cls, config, data: Dict[str, Any], message_type: str = None) -> bool:
        """判断是否应该使用助播TTS
        
        Args:
            config: 配置对象
            data: 消息数据
            message_type: 消息类型
            
        Returns:
            bool: 是否使用助播TTS
        """
        try:
            # 1. 检查数据中的明确标记
            if data.get("_use_assistant_anchor_tts", False):
                return True
            
            # 2. 检查助播功能是否启用
            assistant_config = config.get("assistant_anchor", {})
            if not isinstance(assistant_config, dict) or not assistant_config.get("enable", False):
                return False
            
            # 3. 检查消息类型是否在助播支持列表中
            message_type = message_type or data.get("type", "comment")
            supported_types = assistant_config.get("type", [])
            if isinstance(supported_types, list) and message_type in supported_types:
                return True
            
            # 4. 检查是否为助播专用类型
            assistant_specific_types = [
                "assistant_anchor_text", "assistant_anchor_audio", 
                "assistant_anchor_entrance", "assistant_anchor_read_comment"
            ]
            if message_type in assistant_specific_types:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"判断是否使用助播TTS失败: {e}")
            return False
    
    @classmethod
    def create_audio_message(cls, config, message_type: str, content: str, username: str = "system",
                           use_assistant: bool = None, **kwargs) -> Dict[str, Any]:
        """创建标准的音频消息
        
        Args:
            config: 配置对象
            message_type: 消息类型
            content: 消息内容
            username: 用户名
            use_assistant: 是否使用助播TTS（None表示自动判断）
            **kwargs: 其他字段
            
        Returns:
            Dict[str, Any]: 音频消息
        """
        try:
            from utils.message_utils import MessageUtils
            import time
            
            # 创建基础消息数据
            data = {
                "type": message_type,
                "content": content,
                "username": username,
                "platform": kwargs.get("platform", "local"),
                "timestamp": time.time(),
                **kwargs
            }
            
            # 判断是否使用助播TTS
            if use_assistant is None:
                use_assistant = cls.should_use_assistant_tts(config, data, message_type)
            
            # 获取TTS配置
            if use_assistant:
                tts_type, tts_config = cls.get_assistant_tts_config(config)
                data["_use_assistant_anchor_tts"] = True
            else:
                tts_type, tts_config = cls.get_global_tts_config(config)
                data["_use_assistant_anchor_tts"] = False
            
            # 构建音频消息
            message = {
                "type": message_type,
                "tts_type": tts_type,
                "data": tts_config,
                "config": config.get("filter", {}),
                "username": username,
                "content": content,
                "_use_assistant_anchor_tts": use_assistant
            }
            
            # 添加其他字段
            for key, value in kwargs.items():
                if key not in message and value is not None:
                    message[key] = value
            
            logger.debug(f"创建音频消息: {message_type}, TTS: {tts_type}, 助播: {use_assistant}")
            return message
            
        except Exception as e:
            logger.error(f"创建音频消息失败: {e}")
            # 返回最基本的消息结构
            return {
                "type": message_type,
                "tts_type": cls.DEFAULT_TTS_TYPE,
                "data": {},
                "config": {},
                "username": username,
                "content": content,
                "_use_assistant_anchor_tts": False
            }
    
    @classmethod
    def validate_tts_config(cls, tts_type: str, tts_config: Dict[str, Any]) -> bool:
        """验证TTS配置是否有效
        
        Args:
            tts_type: TTS类型
            tts_config: TTS配置
            
        Returns:
            bool: 配置是否有效
        """
        try:
            if not isinstance(tts_type, str) or tts_type not in cls.SUPPORTED_TTS_TYPES:
                return False
            
            if not isinstance(tts_config, dict):
                return False
            
            # 特殊验证规则
            if tts_type == "gpt_sovits":
                # gpt_sovits必须有type字段
                if "type" not in tts_config:
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"验证TTS配置失败: {e}")
            return False
    
    @classmethod
    def _deep_merge_configs(cls, base_config: Dict[str, Any], override_config: Dict[str, Any]) -> Dict[str, Any]:
        """深度合并两个配置字典
        
        Args:
            base_config: 基础配置
            override_config: 覆盖配置
            
        Returns:
            Dict[str, Any]: 合并后的配置
        """
        try:
            result = deepcopy(base_config) if isinstance(base_config, dict) else {}
            
            for key, value in (override_config or {}).items():
                if isinstance(value, dict) and isinstance(result.get(key), dict):
                    result[key] = cls._deep_merge_configs(result[key], value)
                else:
                    result[key] = value
            
            return result
            
        except Exception as e:
            logger.error(f"深度合并配置失败: {e}")
            return base_config or {}
    
    @classmethod
    def _infer_gpt_sovits_type(cls, config: Dict[str, Any]) -> Dict[str, Any]:
        """推断gpt_sovits的type字段
        
        Args:
            config: gpt_sovits配置
            
        Returns:
            Dict[str, Any]: 推断后的配置
        """
        try:
            result = deepcopy(config)
            
            # 按优先级推断type
            if "api_0322" in result:
                result["type"] = "api_0322"
            elif "api_0706" in result:
                result["type"] = "api_0706"
            elif "v2_api_0821" in result:
                result["type"] = "v2_api_0821"
            elif "webtts" in result:
                result["type"] = "webtts"
            else:
                result["type"] = "api_0322"  # 默认值
            
            logger.debug(f"推断gpt_sovits类型: {result['type']}")
            return result
            
        except Exception as e:
            logger.error(f"推断gpt_sovits类型失败: {e}")
            return config
    
    @classmethod
    def get_safe_tts_config(cls, config, tts_type_key: str = "audio_synthesis_type", 
                          fallback: str = None) -> Tuple[str, Dict[str, Any]]:
        """安全地获取TTS配置（兼容旧方法）
        
        Args:
            config: 配置对象
            tts_type_key: TTS类型配置的键名
            fallback: 回退TTS类型
            
        Returns:
            Tuple[str, Dict[str, Any]]: (tts_type, tts_config)
        """
        try:
            fallback = fallback or cls.DEFAULT_TTS_TYPE
            
            tts_type = config.get(tts_type_key)
            if isinstance(tts_type, str) and tts_type in cls.SUPPORTED_TTS_TYPES:
                tts_config = config.get(tts_type)
                if isinstance(tts_config, dict):
                    return tts_type, deepcopy(tts_config)
            
            # 配置无效，使用回退值
            logger.warning(f"TTS类型配置无效: {tts_type}，使用回退值: {fallback}")
            tts_config = config.get(fallback, {})
            if not isinstance(tts_config, dict):
                tts_config = {}
            
            return fallback, tts_config
            
        except Exception as e:
            logger.error(f"安全获取TTS配置失败: {e}")
            return cls.DEFAULT_TTS_TYPE, {}