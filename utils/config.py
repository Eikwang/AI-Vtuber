import json

class Config:
    # 单例模式
    # _instance = None
    config = None

    # def __new__(cls, *args, **kwargs):
    #     if not cls._instance:
    #         cls._instance = super(Config, cls).__new__(cls)  # 不再传递 *args, **kwargs
    #     return cls._instance

    def __init__(self, config_file):
        if self.config is None:
            with open(config_file, 'r', encoding="utf-8") as f:
                self.config = json.load(f)
    
    def __getitem__(self, key):
        return self.config.get(key)
    
    def get(self, *keys):
        """安全地获取嵌套配置值
        
        Args:
            *keys: 配置键的路径，最后一个参数可以是默认值
            
        Returns:
            配置值或默认值
        """
        # 如果没有传入任何键，返回整个配置
        if not keys:
            return self.config
            
        # 检查最后一个参数是否为默认值
        default_value = None
        config_keys = keys
        
        # 如果最后一个参数不是字符串，可能是默认值
        if len(keys) > 1 and not isinstance(keys[-1], str):
            default_value = keys[-1]
            config_keys = keys[:-1]
        
        result = self.config
        for key in config_keys:
            if isinstance(result, dict) and key in result:
                result = result[key]
            else:
                # 如果路径不存在，返回默认值
                return default_value
                
        return result
    
    def get_safe_tts_config(self, tts_type_key="audio_synthesis_type", fallback="edge-tts"):
        """安全地获取TTS配置，避免TypeError: unhashable type: 'dict'
        
        Args:
            tts_type_key (str): TTS类型配置的键名
            fallback (str): 当TTS类型无效时的回退值
            
        Returns:
            tuple: (tts_type, tts_config)
        """
        tts_type = self.get(tts_type_key)
        if isinstance(tts_type, str):
            tts_config = self.get(tts_type)
            if tts_config is None:
                tts_config = {}
            return tts_type, tts_config
        else:
            # 如果TTS类型配置无效，使用默认值
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"TTS类型配置无效: {tts_type}，使用默认值 {fallback}")
            tts_config = self.get(fallback)
            if tts_config is None:
                tts_config = {}
            return fallback, tts_config
    
    def set(self, *keys_and_value):
        """设置嵌套配置值
        
        Args:
            *keys_and_value: 配置键的路径和最后的值
        """
        if len(keys_and_value) < 2:
            raise ValueError("至少需要一个键和一个值")
            
        keys = keys_and_value[:-1]
        value = keys_and_value[-1]
        
        # 导航到目标位置
        current = self.config
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        # 设置值
        current[keys[-1]] = value
    
    def save(self, config_file):
        """保存配置到文件
        
        Args:
            config_file (str): 配置文件路径
        """
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
