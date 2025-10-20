"""语言检测和映射工具类

提供统一的语言代码检测和不同TTS引擎的语言映射功能，
消除各个TTS引擎中重复的语言映射代码。
"""

import logging

# 获取日志记录器
logger = logging.getLogger(__name__)


class LanguageUtils:
    """语言检测和映射工具类"""
    
    # 支持的语言代码列表
    SUPPORTED_LANGUAGES = ["en", "zh", "ja", "ko", "fr", "de", "es", "it", "ru"]
    
    # 不同TTS引擎的语言映射配置
    TTS_LANGUAGE_MAPPINGS = {
        # VITS引擎语言映射
        "vits": {
            "en": "英文",
            "zh": "中文", 
            "ja": "日文",
            "ko": "韩文",
            "default": "自动"
        },
        
        # Bert-VITS2引擎语言映射
        "bert_vits2": {
            "en": "EN",
            "zh": "ZH",
            "ja": "JP", 
            "ko": "KO",
            "default": "ZH"
        },
        
        # VITS-Fast引擎语言映射
        "vits_fast": {
            "en": "English",
            "zh": "简体中文",
            "ja": "日本語",
            "ko": "한국어",
            "default": "简体中文"
        },
        
        # GPT-SoVITS引擎语言映射
        "gpt_sovits": {
            "en": "英文",
            "zh": "中文",
            "ja": "日文", 
            "ko": "韩文",
            "default": "中文"
        },
        
        # Edge-TTS引擎语言映射
        "edge_tts": {
            "en": "en-US",
            "zh": "zh-CN",
            "ja": "ja-JP",
            "ko": "ko-KR",
            "fr": "fr-FR",
            "de": "de-DE",
            "es": "es-ES",
            "it": "it-IT",
            "ru": "ru-RU",
            "default": "zh-CN"
        },
        
        # Azure-TTS引擎语言映射
        "azure_tts": {
            "en": "en-US",
            "zh": "zh-CN", 
            "ja": "ja-JP",
            "ko": "ko-KR",
            "fr": "fr-FR",
            "de": "de-DE",
            "es": "es-ES",
            "it": "it-IT",
            "ru": "ru-RU",
            "default": "zh-CN"
        },
        
        # OpenAI-TTS引擎语言映射
        "openai_tts": {
            "en": "english",
            "zh": "chinese",
            "ja": "japanese",
            "ko": "korean",
            "fr": "french",
            "de": "german",
            "es": "spanish",
            "it": "italian", 
            "ru": "russian",
            "default": "chinese"
        }
    }
    
    @classmethod
    def get_language_mapping(cls, tts_engine, language_code=None):
        """获取指定TTS引擎的语言映射
        
        Args:
            tts_engine (str): TTS引擎名称
            language_code (str, optional): 语言代码，如果为None则返回整个映射字典
            
        Returns:
            str or dict: 如果指定语言代码则返回对应的映射值，否则返回整个映射字典
        """
        try:
            # 标准化TTS引擎名称
            engine_name = tts_engine.lower().replace("-", "_")
            
            # 获取对应引擎的映射
            engine_mapping = cls.TTS_LANGUAGE_MAPPINGS.get(engine_name, {})
            
            if language_code is None:
                # 返回整个映射字典（不包含default）
                return {k: v for k, v in engine_mapping.items() if k != "default"}
            
            # 返回指定语言的映射值
            if language_code in engine_mapping:
                return engine_mapping[language_code]
            else:
                # 返回默认值
                default_value = engine_mapping.get("default", language_code)
                logger.warning(f"TTS引擎 {tts_engine} 不支持语言代码 {language_code}，使用默认值: {default_value}")
                return default_value
                
        except Exception as e:
            logger.error(f"获取语言映射失败: {e}")
            return language_code if language_code else {}
    
    @classmethod
    def convert_language_for_tts(cls, tts_engine, detected_language):
        """为指定TTS引擎转换语言代码
        
        Args:
            tts_engine (str): TTS引擎名称
            detected_language (str): 检测到的语言代码
            
        Returns:
            str: 转换后的语言代码
        """
        try:
            return cls.get_language_mapping(tts_engine, detected_language)
        except Exception as e:
            logger.error(f"语言代码转换失败: {e}")
            return detected_language
    
    @classmethod
    def get_default_language(cls, tts_engine):
        """获取指定TTS引擎的默认语言
        
        Args:
            tts_engine (str): TTS引擎名称
            
        Returns:
            str: 默认语言代码
        """
        try:
            engine_name = tts_engine.lower().replace("-", "_")
            engine_mapping = cls.TTS_LANGUAGE_MAPPINGS.get(engine_name, {})
            return engine_mapping.get("default", "zh")
        except Exception as e:
            logger.error(f"获取默认语言失败: {e}")
            return "zh"
    
    @classmethod
    def is_language_supported(cls, tts_engine, language_code):
        """检查指定TTS引擎是否支持某种语言
        
        Args:
            tts_engine (str): TTS引擎名称
            language_code (str): 语言代码
            
        Returns:
            bool: 是否支持该语言
        """
        try:
            engine_name = tts_engine.lower().replace("-", "_")
            engine_mapping = cls.TTS_LANGUAGE_MAPPINGS.get(engine_name, {})
            return language_code in engine_mapping and language_code != "default"
        except Exception as e:
            logger.error(f"检查语言支持失败: {e}")
            return False
    
    @classmethod
    def get_supported_languages(cls, tts_engine):
        """获取指定TTS引擎支持的语言列表
        
        Args:
            tts_engine (str): TTS引擎名称
            
        Returns:
            list: 支持的语言代码列表
        """
        try:
            engine_name = tts_engine.lower().replace("-", "_")
            engine_mapping = cls.TTS_LANGUAGE_MAPPINGS.get(engine_name, {})
            return [k for k in engine_mapping.keys() if k != "default"]
        except Exception as e:
            logger.error(f"获取支持语言列表失败: {e}")
            return []
    
    @classmethod
    def add_custom_mapping(cls, tts_engine, language_mappings):
        """添加自定义语言映射
        
        Args:
            tts_engine (str): TTS引擎名称
            language_mappings (dict): 自定义语言映射字典
        """
        try:
            engine_name = tts_engine.lower().replace("-", "_")
            if engine_name not in cls.TTS_LANGUAGE_MAPPINGS:
                cls.TTS_LANGUAGE_MAPPINGS[engine_name] = {}
            
            cls.TTS_LANGUAGE_MAPPINGS[engine_name].update(language_mappings)
            logger.info(f"已为TTS引擎 {tts_engine} 添加自定义语言映射")
        except Exception as e:
            logger.error(f"添加自定义语言映射失败: {e}")