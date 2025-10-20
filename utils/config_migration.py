import json
import logging
from pathlib import Path
from typing import Dict, Any
from .enhanced_config import EnhancedConfig
from .config import Config

logger = logging.getLogger(__name__)

class ConfigMigration:
    """配置迁移工具"""
    
    def __init__(self):
        self.default_config = self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "webui": {
                "ip": "127.0.0.1",
                "port": 8081,
                "title": "AI Vtuber",
                "auto_run": False
            },
            "play_audio": {
                "enable": True,
                "text_split_enable": True,
                "interval_num_min": 1,
                "interval_num_max": 2,
                "normal_interval_min": 0.3,
                "normal_interval_max": 0.5,
                "out_path": "out",
                "player": "pygame",
                "info_to_callback": False
            },
            "audio_synthesis_type": "edge-tts",
            "platform": "bilibili2",
            "room_display_id": "",
            "filter": {
                "before_must_str": [],
                "after_must_str": [],
                "before_filter_str": [],
                "after_filter_str": [],
                "badwords_path": "data/badwords.txt",
                "max_len": 30,
                "max_char_len": 500,
                "comment_forget_duration": 60,
                "comment_forget_reserve_num": 3,
                "gift_forget_duration": 60,
                "entrance_forget_duration": 10,
                "follow_forget_duration": 60,
                "talk_forget_duration": 60,
                "schedule_forget_duration": 10,
                "local_qa_forget_duration": 10,
                "comment": 30,
                "gift": 10,
                "entrance": 30
            },
            "thanks": {
                "entrance_enable": True,
                "entrance_random": True,
                "username_max_len": 12,
                "entrance_copy": [
                    "欢迎{username}",
                    "{username}来了啊"
                ],
                "gift_enable": True,
                "gift_random": True,
                "gift_copy": [
                    "感谢{username}的{gift_name}",
                    "谢谢{username}的{gift_name}"
                ],
                "follow_enable": True,
                "follow_random": True,
                "follow_copy": [
                    "感谢{username}的关注",
                    "谢谢{username}关注"
                ]
            },
            "read_comment": {
                "enable": True,
                "read_username_enable": True,
                "username_max_len": 16,
                "voice_change": False,
                "read_username_copywriting": [
                    "{username}说:",
                    "{username}说道:"
                ]
            },
            "chatgpt": {
                "model": "gpt-3.5-turbo",
                "api_key": "",
                "api": "https://api.openai.com/v1/chat/completions",
                "proxy": "",
                "preset": "你是一个专业的虚拟主播",
                "max_tokens": 800,
                "temperature": 0.9,
                "top_p": 1,
                "presence_penalty": 0,
                "frequency_penalty": 0,
                "history_enable": True,
                "history_max_len": 300
            },
            "edge-tts": {
                "voice": "zh-CN-XiaoxiaoNeural",
                "rate": "+0%",
                "volume": "+0%",
                "pitch": "+0Hz"
            },
            "schedule": [],
            "idle_time_task": {
                "enable": False,
                "comment": {
                    "enable": False,
                    "idle_time": 10,
                    "random_time": 5,
                    "copywriting_path": "data/闲时任务.txt"
                },
                "local_audio": {
                    "enable": False,
                    "idle_time": 20,
                    "random_time": 10,
                    "path": "out/闲时任务音频/"
                }
            },
            "trends_copywriting": {
                "enable": False,
                "random_play": True,
                "play_interval": 30,
                "copywriting_switching_interval": 1800,
                "copywriting_path": "data/动态文案.txt"
            },
            "local_qa": {
                "text": {
                    "enable": True,
                    "type": "json",
                    "file_path": "data/知识库.json",
                    "similarity": 0.5,
                    "username_max_len": 12
                },
                "audio": {
                    "enable": True,
                    "file_path": "out/本地问答音频/",
                    "similarity": 0.5
                }
            },
            "choose_song": {
                "enable": True,
                "similarity": 0.5,
                "start_cmd": ["点歌", "唱首", "唱个"],
                "stop_cmd": ["取消点歌", "别唱了", "关闭歌曲"],
                "random_cmd": ["随机点歌", "随机歌曲"],
                "song_path": "song",
                "match_fail_copy": "抱歉，我还没学会唱{content}"
            },
            "database": {
                "path": "data/database.db",
                "comment_enable": True,
                "entrance_enable": True,
                "gift_enable": True
            }
        }
    
    def migrate_from_old_config(self, old_config_path: str, new_config_path: str) -> bool:
        """从旧配置迁移到新配置"""
        try:
            # 读取旧配置
            old_config = Config(old_config_path)
            
            # 创建增强配置管理器
            enhanced_config = EnhancedConfig(new_config_path, auto_reload=False)
            enhanced_config.set_default_config(self.default_config)
            
            # 迁移配置数据
            if hasattr(old_config, 'config') and old_config.config:
                # 合并旧配置到新配置
                merged_config = self._merge_configs(self.default_config, old_config.config)
                enhanced_config.config = merged_config
                
                # 保存新配置
                if enhanced_config.save():
                    logger.info(f"配置迁移成功: {old_config_path} -> {new_config_path}")
                    return True
                else:
                    logger.error("保存新配置失败")
                    return False
            else:
                logger.warning("旧配置为空，使用默认配置")
                enhanced_config.config = self.default_config
                return enhanced_config.save()
                
        except Exception as e:
            logger.error(f"配置迁移失败: {e}")
            return False
    
    def _merge_configs(self, default: Dict, current: Dict) -> Dict:
        """合并配置"""
        def merge_dict(default_dict: Dict, current_dict: Dict) -> Dict:
            result = default_dict.copy()
            for key, value in current_dict.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = merge_dict(result[key], value)
                else:
                    result[key] = value
            return result
        
        return merge_dict(default, current)
    
    def create_enhanced_config(self, config_path: str, auto_reload: bool = True) -> EnhancedConfig:
        """创建增强配置管理器"""
        enhanced_config = EnhancedConfig(config_path, auto_reload=auto_reload)
        enhanced_config.set_default_config(self.default_config)
        
        # 添加自定义验证规则
        self._setup_validation_rules(enhanced_config)
        
        return enhanced_config
    
    def _setup_validation_rules(self, config: EnhancedConfig):
        """设置验证规则"""
        validator = config.validator
        
        # 端口范围验证
        validator.add_value_constraint(
            "webui.port",
            lambda x: 1 <= x <= 65535,
            "webui端口必须在1-65535范围内"
        )
        
        # IP地址格式验证（简单验证）
        import re
        ip_pattern = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')
        validator.add_value_constraint(
            "webui.ip",
            lambda x: ip_pattern.match(x) is not None,
            "webui IP地址格式无效"
        )
        
        # 音频播放器验证
        valid_players = ["pygame", "vlc", "audio_player"]
        validator.add_value_constraint(
            "play_audio.player",
            lambda x: x in valid_players,
            f"音频播放器必须是以下之一: {valid_players}"
        )
        
        # 平台验证
        valid_platforms = ["bilibili", "bilibili2", "douyin", "dy", "twitch", "youtube"]
        validator.add_value_constraint(
            "platform",
            lambda x: x in valid_platforms,
            f"平台必须是以下之一: {valid_platforms}"
        )
        
        # 文件路径存在性验证
        validator.add_value_constraint(
            "filter.badwords_path",
            lambda x: Path(x).parent.exists(),
            "违禁词文件的父目录不存在"
        )

def create_config_manager(config_path: str = "config.json", auto_reload: bool = True) -> EnhancedConfig:
    """创建配置管理器的便捷函数"""
    migration = ConfigMigration()
    config = migration.create_enhanced_config(config_path, auto_reload)
    
    # 设置默认配置
    default_config = {
        "webui": {
            "port": 12345,
            "host": "127.0.0.1"
        },
        "play_audio": {
            "enable": True
        }
    }
    
    # 合并默认配置
    config.merge_defaults(default_config)
    
    return config

def migrate_config(old_path: str = "config.json", new_path: str = "config_enhanced.json") -> bool:
    """迁移配置的便捷函数"""
    migration = ConfigMigration()
    return migration.migrate_from_old_config(old_path, new_path)