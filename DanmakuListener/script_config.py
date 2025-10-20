import os
import json
from typing import Dict, List, Optional
from datetime import datetime

class ScriptConfig:
    """脚本配置管理器"""
    
    def __init__(self, config_file: str = "script_config.json"):
        self.config_file = config_file
        self.config = self._load_config()
        
    def _load_config(self) -> Dict:
        """加载脚本配置"""
        default_config = {
            "current_script": "danmaku_listener.js",
            "script_directory": ".",
            "available_scripts": [
                {
                    "name": "默认弹幕监听脚本",
                    "filename": "danmaku_listener.js",
                    "path": "danmaku_listener.js",
                    "description": "内置的默认弹幕监听脚本",
                    "is_builtin": True
                },
                {"name": "洛曦直播弹幕监听脚本",
                    "filename": "洛曦 直播弹幕监听 转发至本地WS服务端.js",
                    "path": "d:\\AI\\test\\AI-Vtuber\\Scripts\\直播ws脚本\\洛曦 直播弹幕监听 转发至本地WS服务端.js",
                    "description": "洛曦项目的弹幕监听脚本",
                    "is_builtin": False
                },
                {"name": "通用平台V4.0内存优化版",
                    "filename": "通用平台_V4_内存优化版.js",
                    "path": ".\\直播监听脚本\\通用平台_V4_内存优化版.js",
                    "description": "V4.0内存优化版本，解决WebSocket和DOM泄漏问题",
                    "is_builtin": True,
                    "version": "4.0",
                    "features": [
                        "资源管理器",
                        "内存泄漏检测",
                        "自动清理",
                        "连接池管理"
                    ]
                }
            ],
            "auto_scan_directory": True,
            "scan_directories": [
                "d:\\AI\\AI-Vtuber\\DanmakuListener\\直播监听脚本"
            ],
            "last_updated": datetime.now().isoformat()
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    # 合并默认配置和加载的配置
                    for key, value in default_config.items():
                        if key not in loaded_config:
                            loaded_config[key] = value
                    return loaded_config
            else:
                return default_config
        except Exception as e:
            print(f"加载脚本配置失败: {e}，使用默认配置")
            return default_config
    
    def save_config(self) -> bool:
        """保存脚本配置"""
        try:
            self.config["last_updated"] = datetime.now().isoformat()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"保存脚本配置失败: {e}")
            return False
    
    def get_current_script_path(self) -> str:
        """获取当前脚本的完整路径"""
        current_script = self.config.get("current_script", "danmaku_listener.js")
        
        # 查找当前脚本的完整路径
        for script in self.config.get("available_scripts", []):
            if script["filename"] == current_script:
                return script["path"]
        
        # 如果没找到，返回默认路径
        return os.path.join(self.config.get("script_directory", "."), current_script)
    
    def set_current_script(self, filename: str) -> bool:
        """设置当前使用的脚本"""
        # 检查脚本是否存在于可用脚本列表中
        for script in self.config.get("available_scripts", []):
            if script["filename"] == filename:
                self.config["current_script"] = filename
                return self.save_config()
        
        print(f"脚本 {filename} 不在可用脚本列表中")
        return False
    
    def add_script(self, name: str, filename: str, path: str, description: str = "") -> bool:
        """添加新脚本到配置"""
        # 检查脚本是否已存在
        for script in self.config.get("available_scripts", []):
            if script["filename"] == filename:
                print(f"脚本 {filename} 已存在")
                return False
        
        # 检查文件是否存在
        if not os.path.exists(path):
            print(f"脚本文件不存在: {path}")
            return False
        
        new_script = {
            "name": name,
            "filename": filename,
            "path": path,
            "description": description,
            "is_builtin": False
        }
        
        self.config["available_scripts"].append(new_script)
        return self.save_config()
    
    def remove_script(self, filename: str) -> bool:
        """移除脚本配置"""
        scripts = self.config.get("available_scripts", [])
        for i, script in enumerate(scripts):
            if script["filename"] == filename:
                # 不允许删除内置脚本
                if script.get("is_builtin", False):
                    print(f"不能删除内置脚本: {filename}")
                    return False
                
                # 如果删除的是当前脚本，切换到默认脚本
                if self.config.get("current_script") == filename:
                    self.config["current_script"] = "danmaku_listener.js"
                
                scripts.pop(i)
                return self.save_config()
        
        print(f"脚本 {filename} 不存在")
        return False
    
    def get_available_scripts(self) -> List[Dict]:
        """获取可用脚本列表"""
        return self.config.get("available_scripts", [])
    
    def scan_for_scripts(self) -> int:
        """扫描指定目录中的JavaScript脚本文件"""
        if not self.config.get("auto_scan_directory", True):
            return 0
        
        added_count = 0
        scan_dirs = self.config.get("scan_directories", ["."])
        
        for scan_dir in scan_dirs:
            if not os.path.exists(scan_dir):
                continue
                
            try:
                for root, dirs, files in os.walk(scan_dir):
                    for file in files:
                        if file.endswith('.js'):
                            file_path = os.path.join(root, file)
                            
                            # 检查是否已存在
                            exists = False
                            for script in self.config.get("available_scripts", []):
                                if script["path"] == file_path:
                                    exists = True
                                    break
                            
                            if not exists:
                                # 自动添加发现的脚本
                                script_name = f"自动发现: {file}"
                                if self.add_script(script_name, file, file_path, f"从 {scan_dir} 自动扫描发现"):
                                    added_count += 1
                                    print(f"自动添加脚本: {file_path}")
            except Exception as e:
                print(f"扫描目录 {scan_dir} 时出错: {e}")
        
        return added_count
    
    def get_script_info(self, filename: str) -> Optional[Dict]:
        """获取指定脚本的详细信息"""
        for script in self.config.get("available_scripts", []):
            if script["filename"] == filename:
                # 添加文件状态信息
                script_info = script.copy()
                script_info["exists"] = os.path.exists(script["path"])
                if script_info["exists"]:
                    try:
                        stat = os.stat(script["path"])
                        script_info["size"] = stat.st_size
                        script_info["modified"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    except Exception:
                        pass
                return script_info
        
        return None
    
    def refresh_script_status(self) -> None:
        """刷新所有脚本的状态信息"""
        for script in self.config.get("available_scripts", []):
            script["exists"] = os.path.exists(script["path"])
        
        self.save_config()