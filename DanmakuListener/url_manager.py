import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional
import os

class URLManager:
    """URL管理器，负责直播间URL的增删改查操作"""
    
    def __init__(self, data_file: str = "live_urls.json"):
        # 使用绝对路径，确保无论从哪个目录启动都能加载正确的配置文件
        self.data_file = os.path.join(os.path.dirname(__file__), data_file)
        self.urls = []
        self.load_urls()
    
    def load_urls(self):
        """从文件加载URL配置"""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.urls = data.get('urls', [])
                    # 规范化已存在数据的布尔与数值类型
                    for url in self.urls:
                        if isinstance(url, dict):
                            url['enabled'] = self._to_bool(url.get('enabled', True), True)
                            url['headless_mode'] = self._to_bool(url.get('headless_mode', False), False)
                            url['auto_login'] = self._to_bool(url.get('auto_login', False), False)
                            url['login_required'] = self._to_bool(url.get('login_required', False), False)
                            try:
                                url['priority'] = int(url.get('priority', 1))
                            except Exception:
                                url['priority'] = 1
            else:
                self.urls = []
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading URLs: {e}")
            self.urls = []
    
    def save_urls(self):
        """保存URL配置到文件"""
        try:
            data = {
                "version": "1.0",
                "urls": self.urls
            }
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving URLs: {e}")
    
    def _to_bool(self, value, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "1", "yes", "y", "on"): 
                return True
            if v in ("false", "0", "no", "n", "off"):
                return False
            return default
        if isinstance(value, (int, float)):
            return bool(int(value))
        return default
    
    def add_url(self, name: str, url: str, platform: str, 
                enabled: bool = True, priority: int = 1, 
                headless_mode: bool = False, auto_login: bool = False,
                login_required: bool = False) -> Dict:
        """添加新的URL配置"""
        url_config = {
            "id": str(uuid.uuid4()),
            "name": name,
            "url": url,
            "platform": platform,
            "enabled": self._to_bool(enabled, True),
            "priority": priority,
            "headless_mode": self._to_bool(headless_mode, False),
            "auto_login": self._to_bool(auto_login, False),
            "login_required": self._to_bool(login_required, False),
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "last_monitored": None,
            "monitor_count": 0,
            "error_count": 0
        }
        
        self.urls.append(url_config)
        self.save_urls()
        return url_config
    
    def get_url(self, url_id: str) -> Optional[Dict]:
        """根据ID获取URL配置"""
        for url_config in self.urls:
            if url_config["id"] == url_id:
                return url_config
        return None
    
    def get_all_urls(self) -> List[Dict]:
        """获取所有URL配置"""
        return self.urls.copy()
    
    def update_url(self, url_id: str, **kwargs) -> bool:
        """更新URL配置"""
        for i, url_config in enumerate(self.urls):
            if url_config["id"] == url_id:
                # 更新允许的字段
                allowed_fields = [
                    "name", "url", "platform", "enabled", "priority",
                    "headless_mode", "auto_login", "login_required"
                ]
                
                for field, value in kwargs.items():
                    if field in allowed_fields:
                        if field in ("enabled", "headless_mode", "auto_login", "login_required"):
                            url_config[field] = self._to_bool(value, url_config.get(field, False))
                        elif field == "priority":
                            try:
                                url_config[field] = int(value)
                            except Exception:
                                url_config[field] = url_config.get(field, 1)
                        else:
                            url_config[field] = value
                
                url_config["updated_at"] = datetime.now().isoformat()
                self.save_urls()
                return True
        return False
    
    def delete_url(self, url_id: str) -> bool:
        """删除URL配置"""
        for i, url_config in enumerate(self.urls):
            if url_config["id"] == url_id:
                del self.urls[i]
                self.save_urls()
                return True
        return False
    
    def get_enabled_urls(self) -> List[Dict]:
        """获取所有启用的URL配置"""
        return [url for url in self.urls if url.get("enabled", False)]
    
    def update_monitor_stats(self, url_id: str, success: bool = True):
        """更新监控统计信息"""
        for url_config in self.urls:
            if url_config["id"] == url_id:
                url_config["last_monitored"] = datetime.now().isoformat()
                url_config["monitor_count"] = url_config.get("monitor_count", 0) + 1
                if not success:
                    url_config["error_count"] = url_config.get("error_count", 0) + 1
                self.save_urls()
                break
    
    def get_urls_by_platform(self, platform: str) -> List[Dict]:
        """根据平台获取URL配置"""
        return [url for url in self.urls if url.get("platform") == platform]
    
    def validate_url(self, url: str, platform: str) -> bool:
        """验证URL格式是否正确"""
        import re
        
        platform_patterns = {
            'bilibili': r'https?://live\.bilibili\.com/.*',
            'douyu': r'https?://www\.douyu\.com/.*',
            'huya': r'https?://www\.huya\.com/.*',
            'kuaishou': r'https?://live\.kuaishou\.com/.*',
            'pinduoduo': r'https?://mobile\.yangkeduo\.com/.*',
            '1688': r'https?://live\.1688\.com/.*',
            'taobao': r'https?://tbzb\.taobao\.com/.*',
            'xiaohongshu': r'https?://(redlive|ark)\.xiaohongshu\.com/.*',
            'weixin': r'https?://channels\.weixin\.qq\.com/.*',
            'jinritemai': r'https?://buyin\.jinritemai\.com/.*',
            'tiktok': r'https?://www\.tiktok\.com/.*',
            'douyin': r'https?://(live\.douyin\.com|eos\.douyin\.com)/.*'
        }
        
        if platform not in platform_patterns:
            return False
        
        pattern = platform_patterns[platform]
        return bool(re.match(pattern, url))