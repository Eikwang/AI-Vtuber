"""
重启管理器配置系统
提供重启管理器的配置管理和API接口
"""

import json
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class RestartConfig:
    """重启配置数据类"""
    enabled: bool = True
    interval_hours: float = 6.0
    memory_threshold_mb: int = 2048
    max_restart_attempts: int = 3
    restart_timeout_seconds: int = 300
    enable_memory_monitoring: bool = True
    enable_performance_monitoring: bool = True
    auto_restart_on_memory_leak: bool = True
    preserve_monitoring_state: bool = True
    preserve_cookies: bool = True
    backup_interval_minutes: int = 30
    cleanup_old_backups_days: int = 7
    log_performance_metrics: bool = True
    notification_enabled: bool = False
    notification_webhook_url: Optional[str] = None

class RestartConfigManager:
    """重启配置管理器"""
    
    def __init__(self, config_file: str = "restart_config.json"):
        self.config_file = os.path.join(os.path.dirname(__file__), config_file)
        self.config = RestartConfig()
        self.load_config()
    
    def load_config(self) -> RestartConfig:
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 更新配置对象的属性
                    for key, value in data.items():
                        if hasattr(self.config, key):
                            setattr(self.config, key, value)
                print(f"已加载重启配置: {self.config_file}")
            else:
                # 创建默认配置文件
                self.save_config()
                print(f"已创建默认重启配置: {self.config_file}")
        except Exception as e:
            print(f"加载重启配置失败: {e}")
            self.config = RestartConfig()  # 使用默认配置
        
        return self.config
    
    def save_config(self) -> bool:
        """保存配置文件"""
        try:
            config_dict = asdict(self.config)
            config_dict['last_updated'] = datetime.now().isoformat()
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)
            print(f"重启配置已保存: {self.config_file}")
            return True
        except Exception as e:
            print(f"保存重启配置失败: {e}")
            return False
    
    def update_config(self, **kwargs) -> bool:
        """更新配置"""
        try:
            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
                    print(f"更新配置 {key}: {value}")
                else:
                    print(f"未知配置项: {key}")
            
            return self.save_config()
        except Exception as e:
            print(f"更新配置失败: {e}")
            return False
    
    def get_config(self) -> RestartConfig:
        """获取当前配置"""
        return self.config
    
    def get_config_dict(self) -> Dict[str, Any]:
        """获取配置字典"""
        return asdict(self.config)
    
    def reset_to_default(self) -> bool:
        """重置为默认配置"""
        try:
            self.config = RestartConfig()
            return self.save_config()
        except Exception as e:
            print(f"重置配置失败: {e}")
            return False
    
    def validate_config(self) -> tuple[bool, list[str]]:
        """验证配置有效性"""
        errors = []
        
        if self.config.interval_hours <= 0:
            errors.append("重启间隔必须大于0小时")
        
        if self.config.memory_threshold_mb <= 0:
            errors.append("内存阈值必须大于0MB")
        
        if self.config.max_restart_attempts <= 0:
            errors.append("最大重启尝试次数必须大于0")
        
        if self.config.restart_timeout_seconds <= 0:
            errors.append("重启超时时间必须大于0秒")
        
        if self.config.backup_interval_minutes <= 0:
            errors.append("备份间隔必须大于0分钟")
        
        if self.config.cleanup_old_backups_days <= 0:
            errors.append("清理旧备份天数必须大于0天")
        
        return len(errors) == 0, errors

class RestartAPI:
    """重启管理器API接口"""
    
    def __init__(self, restart_manager=None):
        self.restart_manager = restart_manager
        self.config_manager = RestartConfigManager()
    
    def set_restart_manager(self, restart_manager):
        """设置重启管理器实例"""
        self.restart_manager = restart_manager
    
    async def get_status(self) -> Dict[str, Any]:
        """获取重启管理器状态"""
        if not self.restart_manager:
            return {"error": "重启管理器未初始化"}
        
        try:
            status = await self.restart_manager.get_status()
            return {
                "success": True,
                "data": status
            }
        except Exception as e:
            return {"error": f"获取状态失败: {e}"}
    
    async def trigger_restart(self, reason: str = "手动触发") -> Dict[str, Any]:
        """手动触发重启"""
        if not self.restart_manager:
            return {"error": "重启管理器未初始化"}
        
        try:
            success = await self.restart_manager.trigger_restart(reason)
            return {
                "success": success,
                "message": "重启已触发" if success else "重启触发失败"
            }
        except Exception as e:
            return {"error": f"触发重启失败: {e}"}
    
    def pause_restart(self) -> Dict[str, Any]:
        """暂停自动重启"""
        if not self.restart_manager:
            return {"error": "重启管理器未初始化"}
        
        try:
            self.restart_manager.set_restart_enabled(False)
            return {
                "success": True,
                "message": "自动重启已暂停"
            }
        except Exception as e:
            return {"error": f"暂停重启失败: {e}"}
    
    def resume_restart(self) -> Dict[str, Any]:
        """恢复自动重启"""
        if not self.restart_manager:
            return {"error": "重启管理器未初始化"}
        
        try:
            self.restart_manager.set_restart_enabled(True)
            return {
                "success": True,
                "message": "自动重启已恢复"
            }
        except Exception as e:
            return {"error": f"恢复重启失败: {e}"}
    
    def get_config(self) -> Dict[str, Any]:
        """获取配置"""
        try:
            return {
                "success": True,
                "data": self.config_manager.get_config_dict()
            }
        except Exception as e:
            return {"error": f"获取配置失败: {e}"}
    
    def update_config(self, **kwargs) -> Dict[str, Any]:
        """更新配置"""
        try:
            # 创建临时配置管理器进行验证
            temp_config_manager = RestartConfigManager(self.config_manager.config_file)
            temp_config_manager.config = RestartConfig(**asdict(self.config_manager.config))
            
            # 在临时配置上应用更新
            for key, value in kwargs.items():
                if hasattr(temp_config_manager.config, key):
                    setattr(temp_config_manager.config, key, value)
                else:
                    return {"error": f"未知配置项: {key}"}
            
            # 验证临时配置有效性
            is_valid, errors = temp_config_manager.validate_config()
            if not is_valid:
                return {"error": f"配置验证失败: {', '.join(errors)}"}
            
            # 验证通过，更新实际配置
            success = self.config_manager.update_config(**kwargs)
            
            # 如果重启管理器存在，更新其配置
            if self.restart_manager and success:
                # 检查重启管理器是否有update_config方法
                if hasattr(self.restart_manager, 'update_config'):
                    self.restart_manager.update_config(self.config_manager.get_config_dict())
                else:
                    # 如果没有update_config方法，直接更新相关属性
                    config_dict = self.config_manager.get_config_dict()
                    if hasattr(self.restart_manager, 'restart_interval'):
                        self.restart_manager.restart_interval = config_dict.get('interval_hours', 6.0) * 3600
                    if hasattr(self.restart_manager, 'memory_threshold_mb'):
                        self.restart_manager.memory_threshold_mb = config_dict.get('memory_threshold_mb', 2048)
                    if hasattr(self.restart_manager, 'restart_enabled'):
                        self.restart_manager.restart_enabled = config_dict.get('enabled', True)
            
            return {
                "success": success,
                "message": "配置已更新并保存" if success else "配置更新失败",
                "config": self.config_manager.get_config_dict()
            }
        except Exception as e:
            return {"error": f"更新配置失败: {e}"}
    
    def get_performance_report(self) -> Dict[str, Any]:
        """获取性能报告"""
        if not self.restart_manager:
            return {"error": "重启管理器未初始化"}
        
        try:
            report = self.restart_manager.get_performance_report()
            return {
                "success": True,
                "data": report
            }
        except Exception as e:
            return {"error": f"获取性能报告失败: {e}"}
    
    def get_restart_history(self, limit: int = 10) -> Dict[str, Any]:
        """获取重启历史"""
        if not self.restart_manager:
            return {"error": "重启管理器未初始化"}
        
        try:
            history = self.restart_manager.get_restart_history(limit)
            return {
                "success": True,
                "data": history
            }
        except Exception as e:
            return {"error": f"获取重启历史失败: {e}"}

# 全局API实例
restart_api = None

def get_restart_api():
    """获取全局重启API实例"""
    global restart_api
    if restart_api is None:
        restart_api = RestartAPI()
    return restart_api

def set_restart_manager(manager):
    """设置重启管理器实例"""
    global restart_api
    if restart_api is None:
        restart_api = RestartAPI()
    restart_api.restart_manager = manager