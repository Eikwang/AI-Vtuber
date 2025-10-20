import json
import os
import time
import threading
from typing import Any, Dict, List, Optional, Union, Callable
from pathlib import Path
import logging
from copy import deepcopy

logger = logging.getLogger(__name__)

class ConfigValidator:
    """配置验证器"""
    
    def __init__(self):
        self.validation_rules = {}
        self.required_fields = set()
        self.type_constraints = {}
        self.value_constraints = {}
    
    def add_required_field(self, field_path: str):
        """添加必需字段"""
        self.required_fields.add(field_path)
    
    def add_type_constraint(self, field_path: str, expected_type: type):
        """添加类型约束"""
        self.type_constraints[field_path] = expected_type
    
    def add_value_constraint(self, field_path: str, validator: Callable[[Any], bool], error_msg: str = ""):
        """添加值约束"""
        self.value_constraints[field_path] = (validator, error_msg)
    
    def validate(self, config: Dict) -> List[str]:
        """验证配置，返回错误列表"""
        errors = []
        
        # 检查必需字段
        for field_path in self.required_fields:
            if not self._get_nested_value(config, field_path.split('.')):
                errors.append(f"缺少必需字段: {field_path}")
        
        # 检查类型约束
        for field_path, expected_type in self.type_constraints.items():
            value = self._get_nested_value(config, field_path.split('.'))
            if value is not None:
                # 尝试类型转换以支持验证
                try:
                    if expected_type == int and isinstance(value, str):
                        value = int(value)
                    elif expected_type == float and isinstance(value, (str, int)):
                        value = float(value)
                    elif expected_type == bool and isinstance(value, str):
                        value = value.lower() in ('true', '1', 'yes', 'on')
                    
                    if not isinstance(value, expected_type):
                        errors.append(f"字段 {field_path} 类型错误，期望 {expected_type.__name__}，实际 {type(value).__name__}")
                except (ValueError, TypeError) as e:
                    errors.append(f"字段 {field_path} 类型转换失败: {e}")
        
        # 检查值约束
        for field_path, (validator, error_msg) in self.value_constraints.items():
            value = self._get_nested_value(config, field_path.split('.'))
            if value is not None:
                try:
                    # 尝试类型转换以支持验证
                    if field_path in self.type_constraints:
                        expected_type = self.type_constraints[field_path]
                        if expected_type == int and isinstance(value, str):
                            value = int(value)
                        elif expected_type == float and isinstance(value, (str, int)):
                            value = float(value)
                        elif expected_type == bool and isinstance(value, str):
                            value = value.lower() in ('true', '1', 'yes', 'on')
                    
                    if not validator(value):
                        msg = error_msg or f"字段 {field_path} 值验证失败"
                        errors.append(msg)
                except (ValueError, TypeError) as e:
                    msg = error_msg or f"字段 {field_path} 值验证失败: {e}"
                    errors.append(msg)
        
        return errors
    
    def _get_nested_value(self, config: Dict, keys: List[str]) -> Any:
        """获取嵌套值"""
        current = config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return None
        return current

class EnhancedConfig:
    """增强的配置管理器"""
    
    def __init__(self, config_file, validator=None, auto_reload=False, reload_interval=1.0):
        """
        初始化增强配置管理器
        
        Args:
            config_file: 配置文件路径
            validator: 配置验证器实例
            auto_reload: 是否启用自动重载
            reload_interval: 重载检查间隔（秒）
        """
        self.config_file = Path(config_file)
        self.validator = validator or ConfigValidator()
        self.auto_reload = auto_reload
        self.reload_interval = reload_interval
        self.config = {}
        self.default_config = {}
        self.change_callbacks = []
        self._last_modified = 0
        self._reload_thread = None
        self._stop_reload = threading.Event()
        self._config_lock = threading.RLock()
        
        # 初始化默认验证规则
        self._setup_default_validation()
        
        # 加载配置
        self.load()
        
        # 启动自动重载
        if auto_reload:
            self.start_auto_reload()
    
    def _setup_default_validation(self):
        """设置默认验证规则"""
        # 添加基本的类型约束
        self.validator.add_type_constraint("webui.port", int)
        self.validator.add_type_constraint("webui.ip", str)
        self.validator.add_type_constraint("play_audio.enable", bool)
        
        # 添加值约束
        self.validator.add_value_constraint(
            "webui.port", 
            lambda x: 1 <= x <= 65535, 
            "webui端口必须在1-65535范围内"
        )
        
        # 添加必需字段
        self.validator.add_required_field("webui")
        self.validator.add_required_field("play_audio")
    
    def merge_defaults(self, defaults: Dict):
        """合并默认配置"""
        with self._config_lock:
            self.default_config = deepcopy(defaults)
            self.config = self._merge_with_defaults(self.config)
    
    def set_default_config(self, default_config: Dict):
        """设置默认配置"""
        with self._config_lock:
            self.default_config = deepcopy(default_config)
    
    def add_change_callback(self, callback: Callable[[Dict], None]):
        """添加配置变更回调"""
        self.change_callbacks.append(callback)
    
    def load(self) -> bool:
        """加载配置文件"""
        try:
            with self._config_lock:
                if not self.config_file.exists():
                    logger.warning(f"配置文件不存在: {self.config_file}，使用默认配置")
                    self.config = deepcopy(self.default_config)
                    self.save()  # 创建默认配置文件
                    return True
                
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    new_config = json.load(f)
                
                # 合并默认配置
                merged_config = self._merge_with_defaults(new_config)
                
                # 验证配置
                errors = self.validator.validate(merged_config)
                if errors:
                    logger.error(f"配置验证失败: {errors}")
                    # 可以选择是否继续使用无效配置
                    # return False
                
                old_config = deepcopy(self.config)
                self.config = merged_config
                self._last_modified = self.config_file.stat().st_mtime
                
                # 触发变更回调
                if old_config != self.config:
                    self._notify_changes()
                
                logger.info(f"配置加载成功: {self.config_file}")
                return True
                
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            if not self.config:  # 如果还没有配置，使用默认配置
                self.config = deepcopy(self.default_config)
            return False
    
    def _merge_with_defaults(self, config: Dict) -> Dict:
        """将配置与默认配置合并"""
        def merge_dict(default: Dict, current: Dict) -> Dict:
            result = deepcopy(default)
            for key, value in current.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = merge_dict(result[key], value)
                else:
                    result[key] = value
            return result
        
        return merge_dict(self.default_config, config)
    
    def save(self) -> bool:
        """保存配置到文件"""
        try:
            with self._config_lock:
                # 确保目录存在
                self.config_file.parent.mkdir(parents=True, exist_ok=True)
                
                # 备份原文件
                if self.config_file.exists():
                    backup_file = self.config_file.with_suffix('.json.bak')
                    self.config_file.rename(backup_file)
                
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(self.config, f, ensure_ascii=False, indent=2)
                
                self._last_modified = self.config_file.stat().st_mtime
                logger.info(f"配置保存成功: {self.config_file}")
                return True
                
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return False
    
    def get(self, *keys, default=None) -> Any:
        """安全地获取嵌套配置值"""
        with self._config_lock:
            if not keys:
                return deepcopy(self.config)
            
            result = self.config
            for key in keys:
                if isinstance(result, dict) and key in result:
                    result = result[key]
                else:
                    return default
            
            return deepcopy(result) if isinstance(result, (dict, list)) else result
    
    def set(self, *keys_and_value) -> bool:
        """设置嵌套配置值"""
        if len(keys_and_value) < 2:
            raise ValueError("至少需要一个键和一个值")
        
        keys = keys_and_value[:-1]
        value = keys_and_value[-1]
        
        with self._config_lock:
            # 导航到目标位置
            current = self.config
            for key in keys[:-1]:
                if key not in current:
                    current[key] = {}
                elif not isinstance(current[key], dict):
                    logger.warning(f"覆盖非字典值: {'.'.join(keys[:-1])}.{key}")
                    current[key] = {}
                current = current[key]
            
            # 设置值
            old_value = current.get(keys[-1])
            current[keys[-1]] = value
            
            # 验证新配置
            errors = self.validator.validate(self.config)
            if errors:
                # 回滚更改
                if old_value is not None:
                    current[keys[-1]] = old_value
                else:
                    current.pop(keys[-1], None)
                logger.error(f"配置设置失败，验证错误: {errors}")
                return False
            
            # 触发变更回调
            self._notify_changes()
            return True
    
    def start_auto_reload(self):
        """启动自动重载"""
        if self._reload_thread and self._reload_thread.is_alive():
            return
        
        self._stop_reload.clear()
        self._reload_thread = threading.Thread(target=self._auto_reload_worker, daemon=True)
        self._reload_thread.start()
        logger.info("配置自动重载已启动")
    
    def stop_auto_reload(self):
        """停止自动重载"""
        self._stop_reload.set()
        if self._reload_thread:
            self._reload_thread.join(timeout=1.0)
        logger.info("配置自动重载已停止")
    
    def _auto_reload_worker(self):
        """自动重载工作线程"""
        while not self._stop_reload.wait(self.reload_interval):
            try:
                if self.config_file.exists():
                    current_mtime = self.config_file.stat().st_mtime
                    if current_mtime > self._last_modified:
                        logger.info("检测到配置文件变更，重新加载")
                        self.load()
            except Exception as e:
                logger.error(f"自动重载检查失败: {e}")
    
    def _notify_changes(self):
        """通知配置变更"""
        for callback in self.change_callbacks:
            try:
                callback(deepcopy(self.config))
            except Exception as e:
                logger.error(f"配置变更回调执行失败: {e}")
    
    def __getitem__(self, key):
        """支持字典式访问"""
        return self.get(key)
    
    def __setitem__(self, key, value):
        """支持字典式设置"""
        self.set(key, value)
    
    def __del__(self):
        """析构函数，停止自动重载"""
        if hasattr(self, '_stop_reload'):
            self.stop_auto_reload()