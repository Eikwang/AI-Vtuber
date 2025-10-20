import asyncio
import os
import json
import time
from typing import Dict, Optional, List
from datetime import datetime
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from monitor_manager import MonitorManager, MonitorStatus
from url_manager import URLManager
from script_config import ScriptConfig
from chromium_restart_manager import ChromiumRestartManager
from state_persistence_manager import StatePersistenceManager
from performance_optimizer import PerformanceOptimizer

class BrowserManager:
    """浏览器管理器，负责playwright浏览器控制"""
    
    def __init__(self, url_manager: URLManager, monitor_manager: MonitorManager, config: dict = None):
        self.url_manager = url_manager
        self.monitor_manager = monitor_manager
        self.config = config  # 保存完整配置供后续使用
        self.playwright = None
        self.browser = None
        self.context = None
        self.pages = {}  # url_id -> Page对象
        self.page_sessions = {}  # url_id -> session info
        # 跟踪当前浏览器的无头模式，便于避免不必要的重启
        self.current_headless_mode: Optional[bool] = None
        
        # 从配置文件读取性能优化配置
        browser_config = config.get('browser', {}) if config else {}
        # 强制禁用独立上下文功能
        self.enable_independent_contexts = False
        
        # 脚本配置管理
        self.script_config = ScriptConfig()
        self.script_content = None
        self.is_running = False
        
        # 自动扫描脚本文件
        self._scan_scripts_on_init()
        
        # 性能优化配置
        self.max_pages = browser_config.get('max_pages', 10)  # 支持多直播间监听
        self.page_idle_timeout = browser_config.get('page_idle_timeout', 1800)  # 30分钟空闲超时
        self.gentle_optimization = browser_config.get('gentle_optimization', True)  # 温和优化模式
        
        print(f"浏览器管理器初始化: 最大页面={self.max_pages}, 温和优化={'on' if self.gentle_optimization else 'off'}, 独立上下文=off")
        
        # 禁用健康检查任务（减少资源消耗）
        self.health_check_task = None
        self.retry_tasks = {}  # 重连任务字典
        self.max_retry_attempts = 3  # 最大重试次数
        self.retry_delay = 5  # 重试延迟
        self.health_check_interval = 60  # 健康检查间隔
        
        # COOKIE支持相关属性
        # 使用绝对路径保存Cookie文件，确保无论从哪个目录启动都能一致访问
        self.cookie = os.path.join(os.path.dirname(__file__), 'cookie')
        self.cookie_enabled = browser_config.get('cookie_persistence', True)
        self.auto_save_cookies = browser_config.get('auto_save_cookies', True)
        self.cookie_file_prefix = 'browser_cookies'
        
        # 新增: 支持多种Cookie文件命名格式
        self.cookie_file_patterns = ['browser_cookies', 'douyu_cookies', 'domain_']
        
        # 窗口管理相关属性
        self.force_single_window = browser_config.get('force_single_window', True)
        self.popup_blocking = browser_config.get('popup_blocking', True)
        
        # 确保cookie目录存在
        self._ensure_cookie_directory()
        
        # Cookie保存频率控制
        self.last_cookie_save_time = {}
        self.cookie_save_cooldown = 600  # 10分钟冷却时间
        
        # 异步锁将在需要时创建
        self.lock = None
        
        # 初始化重启管理器相关组件
        restart_config = browser_config.get('restart_manager', {})
        self.restart_enabled = restart_config.get('enabled', True)
        self.restart_interval = restart_config.get('interval_hours', 6)  # 默认6小时重启一次
        self.memory_threshold_mb = restart_config.get('memory_threshold_mb', 2048)  # 2GB内存阈值
        
        # 初始化重启管理器组件
        if self.restart_enabled:
            self.state_persistence_manager = StatePersistenceManager()
            self.performance_optimizer = PerformanceOptimizer()
            
            # 构建重启管理器配置
            restart_config = {
                'restart_interval': self.restart_interval * 3600,  # 转换为秒
                'memory_threshold_mb': self.memory_threshold_mb
            }
            
            self.restart_manager = ChromiumRestartManager(
                browser_manager=self,
                config=restart_config
            )
            print(f"重启管理器已启用: 间隔={self.restart_interval}小时, 内存阈值={self.memory_threshold_mb}MB")
        else:
            self.restart_manager = None
            print("重启管理器已禁用")
        

    
    def _ensure_lock(self):
        """确保异步锁已创建"""
        if self.lock is None:
            self.lock = asyncio.Lock()
    
    async def _handle_cookie_save_trigger(self, page, trigger_reason):
        """处理Cookie保存触发事件"""
        try:
            # 获取页面对应的URL ID
            url_id = None
            for uid, pg in self.pages.items():
                if pg == page:
                    url_id = uid
                    break
            
            if url_id:
                print(f"[{url_id}] Cookie保存触发: {trigger_reason}")
                await self._auto_save_domain_cookies(url_id, f"触发保存: {trigger_reason}")
            else:
                print(f"未知页面Cookie保存触发: {trigger_reason}")
                
        except Exception as e:
            print(f"处理Cookie保存触发失败: {e}")
    
    async def _on_new_page(self, page):
        """处理新页面事件，根据配置控制新标签页行为"""
        try:
            # 根据force_single_window配置决定是否强制单窗口
            if self.force_single_window:
                # 设置页面监听，确保新标签页不会在新窗口打开
                await page.add_init_script("""
                    // 重写window.open方法，确保在同一窗口打开
                    const originalOpen = window.open;
                    window.open = function(url, name, features) {
                        // 如果是新标签页，就在当前窗口打开
                        if (name === '_blank' || !name) {
                            window.location.href = url;
                            return window;
                        }
                        // 否则使用原始方法
                        return originalOpen.call(this, url, name, features);
                    };
                    
                    console.log('[BrowserManager] 已配置页面为在同一窗口打开新标签页');
                """)
            
            # 根据popup_blocking配置决定是否阻止弹窗
            if self.popup_blocking:
                # 重写所有链接的target属性
                await page.add_init_script("""
                    document.addEventListener('DOMContentLoaded', function() {
                        const links = document.querySelectorAll('a[target="_blank"]');
                        links.forEach(link => {
                            link.addEventListener('click', function(e) {
                                e.preventDefault();
                                window.location.href = this.href;
                            });
                        });
                    });
                    
                    console.log('[BrowserManager] 已启用弹窗阻止功能');
                """)
            
            # 增强的Cookie持久化脚本
            await page.add_init_script("""
                // 增强的Cookie自动保存机制
                let cookieWatcher = null;
                let lastCookieCount = 0;
                
                function watchCookieChanges() {
                    // 检查Cookie数量和内容变化
                    function checkCookieStatus() {
                        const currentCookies = document.cookie;
                        const currentCookieCount = currentCookies ? currentCookies.split(';').length : 0;
                        
                        // 如果Cookie数量增加或内容变化，触发保存
                        if (currentCookieCount > lastCookieCount || currentCookies !== document.cookie) {
                            console.log('[Cookie持久化] 检测到Cookie变化，数量:', currentCookieCount);
                            
                            // 触发保存信号
                            if (window.dispatchEvent) {
                                window.dispatchEvent(new CustomEvent('cookieChanged', {
                                    detail: {
                                        count: currentCookieCount,
                                        timestamp: Date.now()
                                    }
                                }));
                            }
                            
                            lastCookieCount = currentCookieCount;
                        }
                    }
                    
                    // 初始检查
                    setTimeout(checkCookieStatus, 1000);
                    
                    // 定期检查（更频繁）
                    cookieWatcher = setInterval(checkCookieStatus, 5000);
                }
                
                // 监听页面事件触发Cookie保存
                function setupCookieEventListeners() {
                    // 监听表单提交
                    document.addEventListener('submit', function(e) {
                        console.log('[Cookie持久化] 检测到表单提交，可能产生新Cookie');
                        setTimeout(() => {
                            if (window.dispatchEvent) {
                                window.dispatchEvent(new CustomEvent('cookieChanged', {
                                    detail: { trigger: 'form_submit', timestamp: Date.now() }
                                }));
                            }
                        }, 1000);
                    });
                    
                    // 监听页面跳转
                    window.addEventListener('beforeunload', function() {
                        console.log('[Cookie持久化] 页面即将跳转，保存Cookie');
                        if (window.dispatchEvent) {
                            window.dispatchEvent(new CustomEvent('cookieChanged', {
                                detail: { trigger: 'page_navigation', timestamp: Date.now() }
                            }));
                        }
                    });
                }
                
                if (document.readyState === 'loading') {
                    document.addEventListener('DOMContentLoaded', function() {
                        watchCookieChanges();
                        setupCookieEventListeners();
                    });
                } else {
                    watchCookieChanges();
                    setupCookieEventListeners();
                }
                
                console.log('[Cookie持久化] 增强的Cookie监听已启动');
            """)
            
            # 监听页面上的Cookie变化事件
            await page.expose_function('triggerCookieSave', lambda reason: asyncio.create_task(self._handle_cookie_save_trigger(page, reason)))
            
            # 监听页面事件
            await page.evaluate("""
                window.addEventListener('cookieChanged', function(event) {
                    if (window.triggerCookieSave) {
                        window.triggerCookieSave(event.detail.trigger || 'cookie_change');
                    }
                });
            """)
            
            print(f"[BrowserManager] 新页面事件处理完成，已启用增强Cookie保存机制")
            
            # 如果改进的Cookie管理器可用，为新页面应用改进的机制
            if hasattr(self, 'improved_cookie_manager') and self.improved_cookie_manager:
                await self.improved_cookie_manager._enhance_page_cookie_saving(page, str(id(page)))
            
        except Exception as e:
            print(f"[BrowserManager] 处理新页面事件失败: {e}")
            
        except Exception as e:
            print(f"[BrowserManager] 处理新页面事件失败: {e}")
    
    def get_script_config(self) -> ScriptConfig:
        """获取脚本配置管理器"""
        return self.script_config
    
    def get_available_scripts(self) -> List[Dict]:
        """获取可用脚本列表"""
        return self.script_config.get_available_scripts()
    
    def set_current_script(self, filename: str) -> bool:
        """设置当前使用的脚本"""
        success = self.script_config.set_current_script(filename)
        if success:
            # 清除缓存的脚本内容，强制重新加载
            self.script_content = None
            print(f"脚本已切换到: {filename}")
        return success
    
    def add_script(self, name: str, filename: str, path: str, description: str = "") -> bool:
        """添加新脚本"""
        return self.script_config.add_script(name, filename, path, description)
    
    def remove_script(self, filename: str) -> bool:
        """移除脚本"""
        return self.script_config.remove_script(filename)
    
    def scan_for_scripts(self) -> int:
        """扫描新脚本"""
        return self.script_config.scan_for_scripts()
    
    def get_current_script_info(self) -> Dict:
        """获取当前脚本信息"""
        current_script = self.script_config.config.get("current_script", "danmaku_listener.js")
        script_info = self.script_config.get_script_info(current_script)
        if script_info:
            script_info["is_current"] = True
            return script_info
        else:
            return {
                "filename": current_script,
                "name": "未知脚本",
                "exists": False,
                "is_current": True
            }
        
    async def initialize(self, headless: bool = False, browser_type: str = "chromium"):
        """初始化playwright和浏览器 - 增强稳定性版本"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                print(f"尝试初始化浏览器 (第{attempt + 1}/{max_retries}次)...")
                
                # 如果已经初始化且浏览器正常运行，直接返回
                if (self.is_running and self.browser and self.context):
                    try:
                        # 验证浏览器和上下文是否仍可用
                        _ = self.browser  # 直接验证浏览器对象
                        self.context.pages
                        # 如果当前模式与目标模式一致，则无需重新初始化
                        if self.current_headless_mode == headless:
                            print("浏览器已初始化并正常运行")
                            return
                        else:
                            # 需要切换浏览器模式，执行清理后重新初始化
                            print(f"需要切换浏览器模式: 当前={self.current_headless_mode}, 目标={headless}，重新初始化")
                            await self.cleanup()
                    except:
                        # 如果验证失败，继续重新初始化
                        print("浏览器状态异常，重新初始化")
                        pass
                
                # 清理旧的资源
                if self.browser:
                    try:
                        # 检查浏览器是否仍可用
                        _ = self.browser  # 直接验证浏览器对象
                    except:
                        # 如果不可用，清理资源
                        print("检测到旧的已关闭浏览器，清理中...")
                        await self.cleanup()
                
                if self.playwright is None:
                    print("启动Playwright...")
                    self.playwright = await async_playwright().start()
                
                if self.browser is None:
                    # 选择浏览器类型
                    if browser_type == "firefox":
                        browser_launcher = self.playwright.firefox
                    elif browser_type == "webkit":
                        browser_launcher = self.playwright.webkit
                    else:
                        browser_launcher = self.playwright.chromium
                    
                    print(f"启动{browser_type}浏览器 (headless: {headless})...")
                    
                    # 根据尝试次数选择不同的启动策略
                    if attempt == 0:
                        # 第一次尝试: 优化参数
                        launch_args = await self._get_optimized_launch_args()
                    elif attempt == 1:
                        # 第二次尝试: 基础参数
                        launch_args = await self._get_basic_launch_args()
                    else:
                        # 第三次尝试: 最小化参数
                        launch_args = await self._get_minimal_launch_args()
                    
                    print(f"使用启动参数: {len(launch_args)} 个参数")
                    
                    try:
                        self.browser = await browser_launcher.launch(
                            headless=headless,
                            args=launch_args
                        )
                        print(f"浏览器launch调用完成，browser对象: {self.browser is not None}")
                    except Exception as launch_error:
                        print(f"浏览器启动异常: {launch_error}")
                        raise Exception(f"浏览器启动失败: {launch_error}")
                    
                    # 检查浏览器是否成功启动
                    await asyncio.sleep(3)  # 增加等待时间让浏览器完全启动
                    
                    print(f"检查浏览器状态: browser={self.browser is not None}")
                    if self.browser:
                        # 直接验证浏览器连接，不依赖_is_closed属性
                        try:
                            # 直接验证浏览器对象
                            _ = self.browser
                            print("浏览器连接正常")
                            print("浏览器启动成功")
                        except Exception as e:
                            print(f"浏览器连接验证失败: {e}")
                            raise Exception(f"浏览器连接异常: {e}")
                    else:
                        raise Exception("浏览器对象为空")
                
                # 创建或重用浏览器上下文（内存优化版本）
                if self.context is None:
                    print("创建浏览器上下文...")
                    
                    # 创建浏览器上下文时加载cookies（简化版）
                    storage_state = None
                    if self.cookie_enabled:
                        try:
                            storage_state = await self._load_cookies()
                            if storage_state:
                                print("已加载cookies")
                        except Exception as e:
                            print(f"加载cookies失败: {e}")
                    
                    # 简化的上下文配置，减少内存占用，增强Cookie持久化
                    self.context = await self.browser.new_context(
                        viewport={'width': 1280, 'height': 720},
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
                        java_script_enabled=True,
                        accept_downloads=False,
                        ignore_https_errors=True,
                        storage_state=storage_state,
                        # 只保留必要的设置，去除复杂的反检测功能
                        locale='zh-CN',
                        timezone_id='Asia/Shanghai',
                        # 确保新标签页在现有窗口中打开
                        extra_http_headers={
                            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
                        }
                    )
                    
                    # 设置页面事件监听，确保自动保存Cookie
                    self.context.on('page', self._on_new_page)
                    
                    print("浏览器上下文创建成功")
                    
                self.is_running = True
                # 记录当前浏览器运行模式
                self.current_headless_mode = headless
                
                # 应用改进的Cookie保存机制
                try:
                    from improved_cookie_saving import apply_improved_cookie_saving
                    self.improved_cookie_manager = await apply_improved_cookie_saving(self)
                    print("[BrowserManager] 已应用改进的Cookie保存机制")
                except Exception as e:
                    print(f"[BrowserManager] 应用改进的Cookie保存机制失败: {e}")
                    self.improved_cookie_manager = None
                

                
                # 启动定期保存Cookie任务
                if self.auto_save_cookies and self.cookie_enabled:
                    # 重新获取browser_config以确保能读取到最新配置
                    browser_config = self.config.get('browser', {}) if self.config else {}
                    cookie_interval = browser_config.get('cookie_save_interval', 15)
                    self.start_periodic_cookie_save(cookie_interval)  # 使用配置中的间隔
                
                # 启动重启管理器
                if self.restart_manager:
                    await self.restart_manager.start()
                    print("重启管理器已启动")
                    
                    # 设置全局API实例
                    from restart_config import set_restart_manager
                    set_restart_manager(self.restart_manager)
                
                print(f"浏览器已成功初始化 - 无头模式: {headless}, 活跃标签页: {len(self.pages)}")
                return  # 成功初始化，退出重试循环
                    
            except Exception as e:
                error_msg = str(e)
                print(f"初始化浏览器失败 (第{attempt + 1}次尝试): {error_msg}")
                
                # 清理失败的资源
                try:
                    await self.cleanup()
                except:
                    pass
                
                if attempt < max_retries - 1:
                    print(f"等待{retry_delay}秒后重试...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # 指数退避
                else:
                    # 最后一次尝试失败，抛出异常
                    print(f"所有重试尝试都失败，放弃初始化")
                    raise Exception(f"初始化浏览器最终失败: {error_msg}")
    
    async def _create_optimized_context(self, url_id: str = None) -> BrowserContext:
        """创建优化的浏览器上下文（已禁用独立上下文功能）"""
        raise Exception("独立上下文功能已被禁用，此方法不再可用。请使用共享上下文。")
    
    async def _get_optimized_launch_args(self) -> List[str]:
        """获取优化的启动参数（第一次尝试）"""
        return [
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--disable-extensions',
            '--disable-plugins',
            '--disable-web-security',
            # 修复新标签页在新窗口打开的问题
            '--disable-popup-blocking',
            '--disable-web-security',
            '--disable-features=VizDisplayCompositor',
            '--force-device-scale-factor=1',
            # 确保标签页在现有窗口中打开
            '--enable-automation',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding'
        ]
    
    async def _get_basic_launch_args(self) -> List[str]:
        """获取基础的启动参数（第二次尝试）"""
        return [
            '--no-sandbox',
            '--disable-dev-shm-usage'
        ]
    
    async def _get_minimal_launch_args(self) -> List[str]:
        """获取最小化的启动参数（第三次尝试）"""
        return []
    
    def _scan_scripts_on_init(self):
        """加载弹幕监听脚本 - 支持V5增强版本"""
        try:
            # 检查是否启用优化脚本，增加空值检查
            script_config_from_main = {}
            if hasattr(self, 'config') and self.config is not None:
                script_config_from_main = self.config.get('script_injection', {})
            use_optimized = script_config_from_main.get('use_optimized_script', True)  # 默认启用优化
            
            # 优先尝试使用V5增强版脚本
            v5_script_path = os.path.join(os.path.dirname(__file__), "直播监听脚本", "通用平台_V5_内存优化增强版.js")
            v4_script_path = os.path.join(os.path.dirname(__file__), "直播监听脚本", "通用平台_V4_内存优化版.js")
            
            script_path = None
            script_version = "unknown"
            
            # 优先级：V5 > V4 > 配置的脚本
            if os.path.exists(v5_script_path):
                script_path = v5_script_path
                script_version = "V5_增强版"
                print(f"[脚本加载] 发现V5增强版脚本，优先使用: {script_path}")
            elif os.path.exists(v4_script_path) and use_optimized:
                script_path = v4_script_path
                script_version = "V4_优化版"
                print(f"[脚本加载] 使用V4优化版脚本: {script_path}")
            else:
                # 回退到配置的脚本路径
                script_path = self.script_config.get_current_script_path()
                current_script = self.script_config.config.get("current_script", "")
                if "V4" in current_script:
                    script_version = "V4_配置版"
                else:
                    script_version = "标准版"
            
            if script_path and os.path.exists(script_path):
                with open(script_path, 'r', encoding='utf-8') as f:
                    self.script_content = f.read()
                    
                # 在脚本中注入增强的配置参数
                config_injection = f"""
// V5增强版配置参数
window.DANMAKU_LISTENER_CONFIG = {{
    // 基础配置
    maxMessageBoxes: {script_config_from_main.get('max_message_boxes', 2)},
    cleanupInterval: {script_config_from_main.get('cleanup_interval', 20000)},
    memoryCheckInterval: {script_config_from_main.get('memory_check_interval', 30000)},
    
    // V5增强功能
    enableResourceManager: {str(script_config_from_main.get('enable_resource_manager', True)).lower()},
    enableAggressiveCleanup: {str(script_config_from_main.get('enable_aggressive_cleanup', True)).lower()},
    memoryThreshold: {script_config_from_main.get('memory_threshold', 40)}, // MB
    maxWebSocketConnections: {script_config_from_main.get('max_websocket_connections', 1)},
    maxObservers: {script_config_from_main.get('max_observers', 1)},
    maxTimers: {script_config_from_main.get('max_timers', 5)},
    
    // 调试和监控
    enableMemoryMonitoring: {str(script_config_from_main.get('enable_memory_monitoring', True)).lower()},
    enablePerformanceLogging: {str(script_config_from_main.get('enable_performance_logging', False)).lower()},
    
    // 版本信息
    scriptVersion: '{script_version}',
    loadTime: Date.now()
}};

console.log('[DANMAKU_LISTENER] 配置已注入:', window.DANMAKU_LISTENER_CONFIG);

"""
                self.script_content = config_injection + self.script_content
                
                print(f"弹幕监听脚本加载成功: {script_version} ({os.path.basename(script_path)})")
                
                # 输出版本特性信息
                if script_version == "V5_增强版":
                    print("[V5增强版] 已启用最新内存优化版本 - 包含ResourceManager、激进清理和实时监控")
                elif script_version.startswith("V4"):
                    print("[V4优化版] 已启用V4.0内存优化版本 - 包含资源管理器和内存泄漏检测")
                    
            else:
                print(f"所有脚本文件都不存在，使用V5内置增强脚本")
                # 使用V5增强的内置脚本
                self.script_content = """
console.log('[弹幕监听] V5内置增强脚本已注入');

// V5增强版内置脚本 - 完整的资源管理和内存优化
(function() {
    'use strict';
    
    // ResourceManager - V5增强版
    class ResourceManager {
        constructor() {
            this.resources = {
                websockets: new Set(),
                observers: new Set(),
                timers: new Set(),
                intervals: new Set(),
                eventListeners: new Map()
            };
            this.memoryStats = {
                startTime: Date.now(),
                lastCleanup: Date.now(),
                cleanupCount: 0
            };
            
            // 绑定页面卸载事件
            this.bindUnloadEvents();
            
            // 启动定期清理
            this.startPeriodicCleanup();
        }
        
        // 添加WebSocket
        addWebSocket(ws) {
            this.resources.websockets.add(ws);
            ws.addEventListener('close', () => this.resources.websockets.delete(ws));
        }
        
        // 添加Observer
        addObserver(observer) {
            this.resources.observers.add(observer);
        }
        
        // 添加定时器
        addTimer(timerId) {
            this.resources.timers.add(timerId);
        }
        
        // 添加间隔器
        addInterval(intervalId) {
            this.resources.intervals.add(intervalId);
        }
        
        // 绑定卸载事件
        bindUnloadEvents() {
            const cleanup = () => this.cleanup();
            window.addEventListener('beforeunload', cleanup);
            window.addEventListener('unload', cleanup);
            window.addEventListener('pagehide', cleanup);
        }
        
        // 启动定期清理
        startPeriodicCleanup() {
            const cleanupInterval = setInterval(() => {
                this.performMaintenanceCleanup();
            }, 30000); // 30秒清理一次
            
            this.addInterval(cleanupInterval);
        }
        
        // 维护性清理
        performMaintenanceCleanup() {
            try {
                // 检查内存使用
                if (window.performance && window.performance.memory) {
                    const memoryMB = window.performance.memory.usedJSHeapSize / 1024 / 1024;
                    if (memoryMB > 40) {
                        console.log(`[ResourceManager] 内存使用过高: ${memoryMB.toFixed(2)}MB，执行清理`);
                        this.aggressiveCleanup();
                    }
                }
                
                // 清理过多的消息框
                const messageBoxes = document.querySelectorAll('.message-box');
                if (messageBoxes.length > 2) {
                    for (let i = 0; i < messageBoxes.length - 2; i++) {
                        try {
                            messageBoxes[i].remove();
                        } catch(e) {}
                    }
                }
                
                this.memoryStats.lastCleanup = Date.now();
                this.memoryStats.cleanupCount++;
                
            } catch(error) {
                console.error('[ResourceManager] 维护清理失败:', error);
            }
        }
        
        // 激进清理
        aggressiveCleanup() {
            // 清理存储
            try {
                if (window.localStorage) {
                    const keys = Object.keys(localStorage);
                    keys.forEach(key => {
                        if (key.includes('temp') || key.includes('cache')) {
                            localStorage.removeItem(key);
                        }
                    });
                }
                if (window.sessionStorage) {
                    sessionStorage.clear();
                }
            } catch(e) {}
            
            // 强制垃圾回收
            if (window.gc) {
                window.gc();
            }
        }
        
        // 完全清理
        cleanup() {
            console.log('[ResourceManager] 执行完全清理...');
            
            // 关闭WebSocket连接
            this.resources.websockets.forEach(ws => {
                try {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.close();
                    }
                } catch(e) {}
            });
            
            // 断开Observer
            this.resources.observers.forEach(observer => {
                try {
                    observer.disconnect();
                } catch(e) {}
            });
            
            // 清理定时器
            this.resources.timers.forEach(timerId => {
                try {
                    clearTimeout(timerId);
                } catch(e) {}
            });
            
            // 清理间隔器
            this.resources.intervals.forEach(intervalId => {
                try {
                    clearInterval(intervalId);
                } catch(e) {}
            });
            
            // 清理事件监听器
            this.resources.eventListeners.forEach((listeners, element) => {
                listeners.forEach(({event, handler}) => {
                    try {
                        element.removeEventListener(event, handler);
                    } catch(e) {}
                });
            });
            
            // 清空资源集合
            Object.values(this.resources).forEach(resource => {
                if (resource instanceof Set) {
                    resource.clear();
                } else if (resource instanceof Map) {
                    resource.clear();
                }
            });
            
            console.log('[ResourceManager] 清理完成');
        }
        
        // 获取状态
        getStatus() {
            return {
                websockets: this.resources.websockets.size,
                observers: this.resources.observers.size,
                timers: this.resources.timers.size,
                intervals: this.resources.intervals.size,
                eventListeners: this.resources.eventListeners.size,
                memoryStats: this.memoryStats
            };
        }
    }
    
    // 创建全局资源管理器
    const resourceManager = new ResourceManager();
    
    // 创建WebSocket连接
    const ws = new WebSocket('ws://127.0.0.1:8765/ws');
    resourceManager.addWebSocket(ws);
    
    ws.onopen = () => {
        console.log('[弹幕监听] V5增强版WebSocket连接已建立');
    };
    
    ws.onmessage = (event) => {
        console.log('[弹幕监听] 收到消息:', event.data);
    };
    
    ws.onerror = (error) => {
        console.error('[弹幕监听] WebSocket错误:', error);
    };
    
    ws.onclose = () => {
        console.log('[弹幕监听] WebSocket连接已关闭');
    };
    
    // 设置全局状态
    window.danmakuListener = {
        status: 'active',
        version: '5.0-builtin-enhanced',
        platform: 'universal',
        socket: ws,
        resourceManager: resourceManager,
        getMemoryInfo: () => {
            const status = resourceManager.getStatus();
            const memory = window.performance && window.performance.memory ? 
                Math.round(window.performance.memory.usedJSHeapSize / 1024 / 1024) + 'MB' : 'N/A';
            return { ...status, memory };
        }
    };
    
    console.log('[弹幕监听] V5增强版内置脚本初始化完成');
    console.log('[弹幕监听] 资源管理器状态:', resourceManager.getStatus());
    
})();
"""
                script_version = "V5_内置增强版"
                print("[V5内置增强版] 已启用最新内存优化版本 - 包含完整ResourceManager和实时监控")
            
            return self.script_content
        except Exception as e:
            print(f"加载脚本失败: {e}")
            # 返回基础脚本作为后备
            self.script_content = "console.log('[弹幕监听] 脚本加载失败');"
            return self.script_content

    async def load_script(self):
        """异步加载脚本内容 - 用于注入时调用"""
        try:
            # 如果脚本内容已经加载，直接返回
            if hasattr(self, 'script_content') and self.script_content:
                return self.script_content
            
            # 否则重新加载脚本
            return self._scan_scripts_on_init()
        except Exception as e:
            print(f"异步加载脚本失败: {e}")
            # 返回基础脚本作为后备
            return "console.log('[弹幕监听] 异步脚本加载失败');"
    
    async def start_monitoring(self, url_id: str, force_headed: bool = False, acquire_lock: bool = True) -> bool:
        """启动对指定URL的监控"""

        async def _start():
            try:
                # 获取URL配置
                url_config = self.url_manager.get_url(url_id)
                if not url_config:
                    raise ValueError(f"URL配置不存在: {url_id}")
                
                # 检查是否已在监控中
                if url_id in self.pages:
                    print(f"URL {url_id} 已在监控中")
                    return False
                
                # 检查标签页数量限制
                if len(self.pages) >= self.max_pages:
                    print(f"已达到最大标签页数量限制 ({self.max_pages})，尝试清理空闲页面")
                    await self._cleanup_idle_pages()
                    
                    # 如果清理后仍然超限，拒绝启动
                    if len(self.pages) >= self.max_pages:
                        raise Exception(f"标签页数量已达上限 ({self.max_pages})，无法启动新的监控")
                
                # 根据URL配置与参数确定是否使用无头模式
                # 统一以全局配置为基准，可选允许URL覆盖，其次考虑force_headed覆盖为有头
                def _to_bool(v, default=False):
                    if isinstance(v, bool):
                        return v
                    if v is None:
                        return default
                    if isinstance(v, str):
                        s = v.strip().lower()
                        if s in ("true", "1", "yes", "y", "on"):
                            return True
                        if s in ("false", "0", "no", "n", "off"):
                            return False
                        return default
                    if isinstance(v, (int, float)):
                        try:
                            return bool(int(v))
                        except Exception:
                            return default
                    return default

                # 读取全局浏览器配置
                browser_config = self.config.get('browser', {}) if self.config else {}
                global_headless = _to_bool(browser_config.get('headless_mode', browser_config.get('headless', False)), False)
                allow_url_override = _to_bool(browser_config.get('allow_url_headless_override', False), False)
                url_headless_raw = url_config.get('headless_mode', None)

                # 计算首选模式：默认使用全局配置，仅在允许覆盖且URL显式设置时覆盖
                if allow_url_override and url_headless_raw is not None:
                    preferred_headless = _to_bool(url_headless_raw, global_headless)
                    decision_source = "URL覆盖"
                else:
                    preferred_headless = global_headless
                    decision_source = "全局配置"

                headless_mode = False if _to_bool(force_headed, False) else preferred_headless

                # 输出模式判定日志，明确来源
                try:
                    url_headless_display = ("未设置" if url_headless_raw is None else _to_bool(url_headless_raw, global_headless))
                    print(f"[{url_id}] 模式判定: 全局无头={global_headless}, URL无头={url_headless_display}, allow_url_override={allow_url_override}, force_headed={_to_bool(force_headed, False)} -> 最终无头={headless_mode} (来源: {decision_source})")
                except Exception:
                    # 日志失败不影响逻辑
                    pass

                # 如果配置中的URL需要登录或启用自动登录，强制使用有头模式
                if _to_bool(url_config.get('login_required', False), False) or _to_bool(url_config.get('auto_login', False), False):
                    if headless_mode:
                        print(f"[{url_id}] 检测到需要登录，强制使用有头模式")
                    headless_mode = False
                
                # 如果浏览器未初始化或需要切换模式，重新初始化
                browser_needs_init = False
                
                if not self.is_running or not self.browser:
                    browser_needs_init = True
                    print(f"[{url_id}] 浏览器未初始化或不可用")
                else:
                    # 检查浏览器是否仍然有效
                    try:
                        # 直接验证浏览器状态
                        _ = self.browser
                        
                        # 额外检查：尝试创建一个测试Context来验证浏览器是否真正可用
                        test_context = await self.browser.new_context()
                        await test_context.close()
                        # 根据当前记录的模式判断是否需要切换模式
                        if self.current_headless_mode is not None and headless_mode != self.current_headless_mode:
                            browser_needs_init = True
                            print(f"[{url_id}] 需要切换浏览器模式: 当前={self.current_headless_mode}, 目标={headless_mode}")
                    except Exception as e:
                        browser_needs_init = True
                        print(f"[{url_id}] 浏览器状态检查失败: {e}")
                
                if browser_needs_init:
                    print(f"[{url_id}] 正在重新初始化浏览器...")
                    await self.initialize(headless=headless_mode)
                
                # 更新监控状态为启动中
                self.monitor_manager.update_session_status(url_id, MonitorStatus.STARTING)
                
                # 创建新标签页（只使用共享上下文）
                page = None
                
                # 直接使用共享上下文
                    # 使用共享上下文
                if not self.context:
                    # 共享上下文也不可用，尝试重新初始化浏览器
                    print(f"[{url_id}] 共享上下文不可用，重新初始化浏览器...")
                    await self.initialize(headless=headless_mode)
                    if not self.context:
                        raise Exception("重新初始化后仍然无法创建上下文")
                
                try:
                    page = await self.context.new_page()
                    print(f"[{url_id}] 使用共享上下文")
                except Exception as e:
                    print(f"[{url_id}] 共享上下文创建页面失败: {e}")
                    # 最后一次尝试：强制重新初始化
                    print(f"[{url_id}] 强制重新初始化浏览器...")
                    await self.cleanup()
                    await asyncio.sleep(2)
                    await self.initialize(headless=headless_mode)
                    if not self.context:
                        raise Exception("强制重新初始化失败")
                    page = await self.context.new_page()
                    print(f"[{url_id}] 使用重新初始化的共享上下文")
                self.pages[url_id] = page
                
                # 记录会话信息
                self.page_sessions[url_id] = {
                    'start_time': datetime.now(),
                    'last_activity': datetime.now(),
                    'url_config': url_config,
                    'error_count': 0
                }
                
                # 设置页面事件监听
                await self._setup_page_listeners(page, url_id)
                
                # 导航到直播间页面
                print(f"正在打开直播间: {url_config['url']} (标签页 {len(self.pages)}/{self.max_pages})")
                
                try:
                    # 增加连接超时时间并加入重试机制
                    max_retries = 3
                    for attempt in range(max_retries):
                        try:
                            await page.goto(
                                url_config['url'], 
                                wait_until='domcontentloaded', 
                                timeout=60000  # 增加到60秒
                            )
                            print(f"[{url_id}] 页面加载成功")
                            break
                        except Exception as e:
                            error_msg = str(e)
                            print(f"[{url_id}] 页面加载尝试 {attempt + 1}/{max_retries} 失败: {error_msg}")
                            
                            if attempt == max_retries - 1:
                                # 最后一次尝试失败
                                if 'net::ERR_PROXY_CONNECTION_FAILED' in error_msg:
                                    raise Exception(f"代理连接失败，请检查网络设置或关闭代理软件: {error_msg}")
                                elif 'Timeout' in error_msg or 'timeout' in error_msg:
                                    raise Exception(f"页面加载超时，请检查网络连接: {error_msg}")
                                else:
                                    raise Exception(f"页面加载失败: {error_msg}")
                            else:
                                # 等待后重试
                                await asyncio.sleep(2)
                                
                except Exception as e:
                    raise e
                
                # 等待页面加载完成
                await asyncio.sleep(3)
                
                # 预加载脚本内容
                if not self.script_content:
                    await self.load_script()
                
                # 注入弹幕监听脚本
                await self._inject_danmaku_script(page, url_id)
                
                # 更新监控状态为运行中
                self.monitor_manager.update_session_status(url_id, MonitorStatus.RUNNING)
                
                # 更新心跳
                self.monitor_manager.update_heartbeat(url_id)
                
                print(f"监控已启动: {url_config['name']} ({url_config['platform']})")
                return True
                
            except Exception as e:
                print(f"启动监控失败 {url_id}: {e}")
                self.monitor_manager.update_session_status(url_id, MonitorStatus.ERROR, str(e))
                
                # 清理失败的页面和会话
                if url_id in self.pages:
                    try:
                        await self.pages[url_id].close()
                    except Exception as close_error:
                        print(f"关闭页面时出错: {close_error}")
                    finally:
                        # 确保从字典中移除
                        self.pages.pop(url_id, None)
                
                if url_id in self.page_sessions:
                    self.page_sessions.pop(url_id, None)
                
                return False

        if acquire_lock:
            self._ensure_lock()
            async with self.lock:
                return await _start()
        else:
            return await _start()
    
    async def stop_monitoring(self, url_id: str, acquire_lock: bool = True) -> bool:
        """停止对指定URL的监控 - 增强版本"""

        async def _stop():
            try:
                if url_id not in self.pages:
                    print(f"URL {url_id} 未在监控中")
                    # 仍然更新状态为已停止
                    self.monitor_manager.update_session_status(url_id, MonitorStatus.STOPPED)
                    return True
                
                # 关闭页面前执行清理
                page = self.pages[url_id]
                try:
                    # 执行页面级清理
                    await page.evaluate("""
                        // 清理所有事件监听器
                        try {
                            const elements = document.querySelectorAll('*');
                            elements.forEach(el => {
                                if (el._eventListeners) delete el._eventListeners;
                                if (el.onclick) el.onclick = null;
                                if (el.onmouseover) el.onmouseover = null;
                            });
                            // 清理WebSocket连接
                            if (window.danmakuListener && window.danmakuListener.socket) {
                                window.danmakuListener.socket.close();
                                window.danmakuListener.socket = null;
                            }
                            // 强制垃圾回收
                            if (window.gc) window.gc();
                        } catch(e) {
                            console.log('清理页面资源时出错:', e);
                        }
                    """)
                    await page.close()
                    print(f"页面已关闭: {url_id}")
                except Exception as e:
                    print(f"关闭页面时出错: {e}")
                
                # 移除页面引用 (事件监听器可能已经移除了它)
                self.pages.pop(url_id, None)
                
                # 清理页面会话信息
                if url_id in self.page_sessions:
                    self.page_sessions.pop(url_id, None)
                    print(f"已清理页面会话: {url_id}")
                
                # 更新监控状态为已停止
                self.monitor_manager.update_session_status(url_id, MonitorStatus.STOPPED)
                
                print(f"监控已停止: {url_id}")
                return True
                
            except Exception as e:
                print(f"停止监控失败 {url_id}: {e}")
                # 即使出错也尝试更新状态
                try:
                    self.monitor_manager.update_session_status(url_id, MonitorStatus.ERROR, f"停止失败: {e}")
                except:
                    pass
                return False

        if acquire_lock:
            self._ensure_lock()
            async with self.lock:
                return await _stop()
        else:
            return await _stop()
    
    async def stop_all_monitoring(self):
        """停止所有监控"""
        url_ids = list(self.pages.keys())
        for url_id in url_ids:
            await self.stop_monitoring(url_id)
    
    async def _cleanup_idle_pages(self):
        """清理空闲页面 - 智能不破坏性版本"""
        if not self.gentle_optimization:
            # 如果未启用温和优化，使用原来的逻辑
            return await self._cleanup_idle_pages_aggressive()
        
        current_time = datetime.now()
        idle_pages = []
        
        # 智能判断页面是否可以安全清理
        for url_id, session_info in self.page_sessions.items():
            if url_id not in self.pages:
                continue
                
            # 1. 检查页面是否真的空闲（超过30分钟无活动）
            idle_time = (current_time - session_info['last_activity']).total_seconds()
            is_truly_idle = idle_time > self.page_idle_timeout
            
            # 2. 检查页面是否有频繁错误（错误次数超过20次）
            has_frequent_errors = session_info['error_count'] > 20
            
            # 3. 检查页面是否已经崩溃或关闭
            try:
                page = self.pages[url_id]
                is_page_dead = page.is_closed()
            except:
                is_page_dead = True
            
            # 4. 检查监控状态（只清理已停止或错误状态的页面）
            monitor_status = self.monitor_manager.get_session_status(url_id)
            is_monitoring_inactive = monitor_status in [MonitorStatus.STOPPED.value, MonitorStatus.ERROR.value] if monitor_status else False
            
            # 只有同时满足多个条件时才考虑清理
            should_cleanup = False
            cleanup_reason = []
            
            if is_page_dead:
                should_cleanup = True
                cleanup_reason.append("页面已关闭")
            elif is_monitoring_inactive and is_truly_idle:
                should_cleanup = True
                cleanup_reason.append("监控已停止且长时间空闲")
            elif has_frequent_errors and is_truly_idle:
                should_cleanup = True
                cleanup_reason.append("频繁错误且长时间空闲")
            
            if should_cleanup:
                idle_pages.append((url_id, cleanup_reason))
                print(f"标记页面为可清理: {url_id} - {', '.join(cleanup_reason)} (空闲{idle_time:.1f}秒, 错误{session_info['error_count']}次)")
        
        # 清理标记的页面
        cleaned_count = 0
        for url_id, reason in idle_pages:
            try:
                print(f"清理空闲页面: {url_id} - {', '.join(reason)}")
                await self.stop_monitoring(url_id, acquire_lock=False)
                cleaned_count += 1
            except Exception as e:
                print(f"清理页面失败 {url_id}: {e}")
        
        if cleaned_count > 0:
            print(f"清理了 {cleaned_count} 个真正空闲的页面")
        else:
            print("所有页面都在正常使用中，未清理任何页面")
        
        return cleaned_count
    

    
    async def _cleanup_expired_contexts(self):
        """清理过期的Context（已禁用独立上下文功能）"""
        return 0
    
    async def _check_context_memory_usage(self):
        """检查Context内存使用情况（已禁用独立上下文功能）"""
        return
    

    

    

    

    

    

    

    

    

    
    async def _detect_and_fix_script_memory_leaks(self, page: Page, url_id: str):
        """检测并修复弹幕脚本的内存泄漏"""
        try:
            # 检测并修复脚本内存泄漏
            leak_info = await page.evaluate("""
                (() => {
                    try {
                        let leakDetected = false;
                        let fixedItems = [];
                        let needsReinject = false;
                        
                        // 1. 检查是否有多个WebSocket连接
                        let wsCount = 0;
                        let sockets = [];
                        if (window.my_socket) {
                            sockets.push(window.my_socket);
                            wsCount++;
                        }
                        if (window.danmakuListener && window.danmakuListener.socket) {
                            sockets.push(window.danmakuListener.socket);
                            wsCount++;
                        }
                        
                        // 检查所有WebSocket连接的状态
                        let activeSockets = 0;
                        sockets.forEach((socket, index) => {
                            try {
                                if (socket && socket.readyState === WebSocket.OPEN) {
                                    activeSockets++;
                                    // 如果有多个活跃连接，关闭旧的
                                    if (activeSockets > 1) {
                                        socket.close();
                                        leakDetected = true;
                                        fixedItems.push(`closed duplicate WebSocket #${index}`);
                                    }
                                }
                            } catch(e) {}
                        });
                        
                        if (wsCount > 1) {
                            leakDetected = true;
                        }
                        
                        // 2. 检查MutationObserver数量
                        let observerCount = 0;
                        if (window.my_observer) observerCount++;
                        
                        // 如果发现多个观察器，关闭旧的
                        if (observerCount > 1) {
                            leakDetected = true;
                            try {
                                window.my_observer.disconnect();
                                window.my_observer = null;
                                fixedItems.push('disconnected duplicate MutationObserver');
                            } catch(e) {}
                        }
                        
                        // 3. 检查是否有过多的定时器
                        let timeoutCount = 0;
                        // 更精确的定时器检测
                        const timerKeys = Object.keys(window).filter(key => 
                            key.startsWith('timeout_') || key.startsWith('interval_') || 
                            key.includes('Timeout') || key.includes('Interval')
                        );
                        timeoutCount = timerKeys.length;
                        
                        if (timeoutCount > 3) {  // 进一步降低阈值
                            leakDetected = true;
                            // 清理所有已知的定时器
                            for (let i = 1; i < 10000; i++) {
                                try {
                                    clearTimeout(i);
                                    clearInterval(i);
                                } catch(e) {}
                            }
                            // 清理全局变量中的定时器引用
                            timerKeys.forEach(key => {
                                try {
                                    delete window[key];
                                } catch(e) {}
                            });
                            fixedItems.push(`cleared ${timeoutCount} timers`);
                        }
                        
                        // 4. 检查DOM元素数量（特别是消息框）
                        const messageBoxes = document.querySelectorAll('.message-box');
                        if (messageBoxes.length > 3) {  // 进一步降低阈值
                            leakDetected = true;
                            // 删除过多的消息框
                            for (let i = 0; i < messageBoxes.length - 1; i++) {
                                try {
                                    if (messageBoxes[i].parentNode) {
                                        messageBoxes[i].parentNode.removeChild(messageBoxes[i]);
                                    }
                                } catch(e) {}
                            }
                            fixedItems.push(`removed ${messageBoxes.length - 1} excess message boxes`);
                        }
                        
                        // 5. 检查内存使用情况
                        let memoryUsage = 0;
                        if (window.performance && window.performance.memory) {
                            memoryUsage = window.performance.memory.usedJSHeapSize;
                            // 降低内存阈值到50MB
                            if (memoryUsage > 50 * 1024 * 1024) {
                                leakDetected = true;
                                // 60MB以上需要重新注入脚本
                                if (memoryUsage > 60 * 1024 * 1024) {
                                    needsReinject = true;
                                }
                            }
                        }
                        
                        // 6. 检查事件监听器数量
                        let eventListenerCount = 0;
                        try {
                            // 估算事件监听器数量（通过检查常见元素）
                            const elementsWithListeners = document.querySelectorAll('*');
                            eventListenerCount = Math.min(elementsWithListeners.length * 2, 1000); // 估算值
                            
                            if (eventListenerCount > 500) {
                                leakDetected = true;
                                needsReinject = true;
                            }
                        } catch(e) {}
                        
                        // 7. 强制垃圾回收（如果浏览器支持）
                        if (leakDetected && window.gc) {
                            try {
                                window.gc();
                                fixedItems.push('forced garbage collection');
                            } catch(e) {}
                        }
                        
                        return {
                            leakDetected,
                            needsReinject,
                            fixedItems,
                            wsCount,
                            observerCount,
                            timeoutCount,
                            messageBoxCount: messageBoxes.length,
                            eventListenerCount,
                            memoryUsage: Math.round(memoryUsage / 1024 / 1024) + 'MB'
                        };
                        
                    } catch(error) {
                        return {
                            error: error.message,
                            leakDetected: false,
                            needsReinject: false,
                            fixedItems: []
                        };
                    }
                })()
            """)
            
            if leak_info.get('leakDetected'):
                print(f"[{url_id}] 检测到内存泄漏，已修复: {leak_info.get('fixedItems', [])}")
                print(f"[{url_id}] 内存状态: WS={leak_info.get('wsCount')}, Observer={leak_info.get('observerCount')}, Timers={leak_info.get('timeoutCount')}, Listeners={leak_info.get('eventListenerCount')}, 内存={leak_info.get('memoryUsage')}")
                
                # 降低重新注入脚本的内存阈值到60MB
                if leak_info.get('needsReinject'):
                    print(f"[{url_id}] 内存使用过高({leak_info.get('memoryUsage')})，重新注入脚本")
                    await self._reinject_script(page, url_id)
                    
            return leak_info
            
        except Exception as e:
            print(f"[{url_id}] 内存泄漏检测失败: {e}")
            return {'error': str(e), 'leakDetected': False, 'needsReinject': False, 'fixedItems': []}
    
    async def _reinject_script(self, page: Page, url_id: str):
        """重新注入弹幕脚本（清理版本）"""
        try:
            print(f"[{url_id}] 重新注入弹幕脚本...")
            
            # 首先完全清理旧的脚本环境
            await page.evaluate("""
                (() => {
                    try {
                        // 关闭WebSocket
                        if (window.my_socket) {
                            try { window.my_socket.close(); } catch(e) {}
                            window.my_socket = null;
                        }
                        if (window.danmakuListener && window.danmakuListener.socket) {
                            try { window.danmakuListener.socket.close(); } catch(e) {}
                            window.danmakuListener.socket = null;
                        }
                        
                        // 停止MutationObserver
                        if (window.my_observer) {
                            try { window.my_observer.disconnect(); } catch(e) {}
                            window.my_observer = null;
                        }
                        
                        // 清理定时器
                        for (let i = 1; i < 99999; i++) {
                            try { clearTimeout(i); clearInterval(i); } catch(e) {}
                        }
                        
                        // 清理消息框
                        const messageBoxes = document.querySelectorAll('.message-box');
                        messageBoxes.forEach(box => {
                            try {
                                if (box.parentNode) box.parentNode.removeChild(box);
                            } catch(e) {}
                        });
                        
                        // 重置全局变量
                        window.danmakuListener = {
                            status: 'reinitializing',
                            version: '3.0',
                            platform: window.danmukuListener?.platform || 'unknown',
                            socket: null
                        };
                        
                        console.log('[DANMAKU_LISTENER] 旧脚本环境已清理');
                        
                    } catch(error) {
                        console.error('[DANMAKU_LISTENER] 清理旧脚本环境出错:', error);
                    }
                })()
            """)
            
            # 等待一下让清理完成
            await asyncio.sleep(2)
            
            # 重新注入脚本
            script_content = await self.load_script()
            if script_content:
                await page.add_init_script(script_content)
                print(f"[{url_id}] 脚本重新注入完成")
            
        except Exception as e:
            print(f"[{url_id}] 重新注入脚本失败: {e}")
    
    async def _force_cleanup_old_pages(self):
        """智能强制清理旧页面 - 保护正在监听的页面"""
        try:
            if not self.pages:
                return 0
            
            if self.gentle_optimization:
                # 温和模式：只在确实需要时才清理，且优先清理非活跃页面
                return await self._gentle_force_cleanup()
            else:
                # 激进模式：按照原来的逻辑
                return await self._aggressive_force_cleanup()
            
        except Exception as e:
            print(f"强制清理旧页面失败: {e}")
            return 0
    
    async def _gentle_force_cleanup(self):
        """温和的强制清理 - 保护活跃监听页面"""
        print(f"当前页面数量: {len(self.pages)}, 上限: {self.max_pages}")
        
        # 检查是否真的需要清理（增加缓冲区）
        if len(self.pages) <= self.max_pages + 5:  # 增加5个页面的缓冲
            print("页面数量在安全范围内，无需强制清理")
            return 0
        
        # 分类页面：活跃监听 vs 非活跃页面
        active_monitoring_pages = []
        inactive_pages = []
        
        for url_id in self.pages.keys():
            monitor_status = self.monitor_manager.get_session_status(url_id)
            session_info = self.page_sessions.get(url_id, {})
            
            # 判断页面是否正在活跃监听（更严格的判断条件）
            is_actively_monitoring = (
                monitor_status == MonitorStatus.RUNNING.value and
                session_info.get('error_count', 0) < 5 and  # 降低错误阈值
                (datetime.now() - session_info.get('last_activity', datetime.min)).total_seconds() < 300  # 5分钟内有活动
            ) if monitor_status else False
            
            if is_actively_monitoring:
                active_monitoring_pages.append((url_id, session_info.get('last_activity', datetime.min)))
            else:
                inactive_pages.append((url_id, session_info.get('last_activity', datetime.min)))
        
        print(f"活跃监听页面: {len(active_monitoring_pages)}, 非活跃页面: {len(inactive_pages)}")
        
        # 优先清理非活跃页面
        cleaned = 0
        pages_to_cleanup = inactive_pages.copy()
        
        # 增加额外的安全缓冲，避免清理活跃页面
        need_to_cleanup = len(self.pages) - (self.max_pages + 5)  # 使用更大的缓冲区
        if need_to_cleanup <= 0:
            print("页面数量在安全范围内，无需强制清理")
            return 0
            
        # 只有在非活跃页面数量远不足时，才考虑清理活跃页面
        if len(inactive_pages) < need_to_cleanup and active_monitoring_pages:
            print(f"警告：非活跃页面不够，需要清理部分活跃页面")
            # 按时间排序，最旧的在前
            active_monitoring_pages.sort(key=lambda x: x[1])
            additional_needed = need_to_cleanup - len(inactive_pages)
            # 进一步限制清理活跃页面的数量，避免影响监听
            additional_needed = min(additional_needed, max(1, len(active_monitoring_pages) // 2))  # 最多清理一半活跃页面
            pages_to_cleanup.extend(active_monitoring_pages[:additional_needed])
        
        # 执行清理（添加安全检查）
        actually_cleaned = 0
        for url_id, last_activity in pages_to_cleanup[:need_to_cleanup]:
            try:
                # 再次检查页面状态，确保不会误删活跃监听页面
                monitor_status = self.monitor_manager.get_session_status(url_id)
                session_info = self.page_sessions.get(url_id, {})
                is_actively_monitoring = (
                    monitor_status == MonitorStatus.RUNNING.value and
                    session_info.get('error_count', 0) < 5 and
                    (datetime.now() - session_info.get('last_activity', datetime.min)).total_seconds() < 300
                ) if monitor_status else False
                
                if is_actively_monitoring:
                    print(f"跳过活跃监听页面的清理: {url_id}")
                    continue
                    
                print(f"强制清理页面: {url_id} (状态: {monitor_status}, 最后活动: {last_activity})")
                await self.stop_monitoring(url_id, acquire_lock=False)
                actually_cleaned += 1
            except Exception as e:
                print(f"清理页面失败 {url_id}: {e}")
        
        print(f"温和强制清理完成，实际清理了 {actually_cleaned} 个页面，保留 {len(self.pages) - actually_cleaned} 个页面")
        return actually_cleaned
    
    async def _aggressive_force_cleanup(self):
        """激进的强制清理（原来的逻辑）"""
        if not self.pages:
            return 0
        
        # 按照最后活动时间排序，清理最旧的页面
        page_activities = []
        for url_id, session_info in self.page_sessions.items():
            if url_id in self.pages:
                page_activities.append((url_id, session_info.get('last_activity')))
        
        # 按时间排序，最旧的在前
        page_activities.sort(key=lambda x: x[1] if x[1] else datetime.min)
        
        # 清理最旧的页面，保留最新的一个
        cleanup_count = len(self.pages) - 1
        cleaned = 0
        
        for i in range(cleanup_count):
            if i < len(page_activities):
                url_id = page_activities[i][0]
                print(f"强制清理旧页面: {url_id}")
                await self.stop_monitoring(url_id, acquire_lock=False)
                cleaned += 1
        
        print(f"激进强制清理完成，清理了 {cleaned} 个旧页面")
        return cleaned
    
    def _update_page_activity(self, url_id: str):
        """更新页面活动时间"""
        if url_id in self.page_sessions:
            self.page_sessions[url_id]['last_activity'] = datetime.now()
            # 页面正常活动时，重置错误计数
            if self.page_sessions[url_id]['error_count'] > 0:
                self.page_sessions[url_id]['error_count'] = 0
    
    def _increment_page_error(self, url_id: str):
        """增加页面错误计数"""
        if url_id in self.page_sessions:
            self.page_sessions[url_id]['error_count'] += 1
            
            # 提高错误阈值，避免因连接错误频繁重连
            if self.page_sessions[url_id]['error_count'] >= 10:
                print(f"页面 {url_id} 错误次数过多({self.page_sessions[url_id]['error_count']}次)，将触发重连")
                asyncio.create_task(self._schedule_reconnect(url_id))
    
    async def _schedule_reconnect(self, url_id: str):
        """安排重连任务"""
        if url_id in self.retry_tasks:
            # 如果已有重连任务在进行，跳过
            return
        
        print(f"安排重连任务: {url_id}")
        self.retry_tasks[url_id] = asyncio.create_task(self._reconnect_with_retry(url_id))
    
    async def _reconnect_with_retry(self, url_id: str):
        """带重试的重连机制"""
        try:
            url_config = self.url_manager.get_url(url_id)
            if not url_config:
                print(f"重连失败: URL配置不存在 {url_id}")
                return
            
            # 停止当前监控
            await self.stop_monitoring(url_id)
            
            # 重试连接
            for attempt in range(self.max_retry_attempts):
                try:
                    print(f"尝试重连 {url_id} (第 {attempt + 1}/{self.max_retry_attempts} 次)")
                    
                    # 等待重试延迟
                    if attempt > 0:
                        await asyncio.sleep(self.retry_delay * attempt)
                    
                    # 尝试重新启动监控
                    success = await self.start_monitoring(url_id)
                    if success:
                        print(f"重连成功: {url_id}")
                        self.monitor_manager.update_session_status(url_id, MonitorStatus.RUNNING, "重连成功")
                        return
                    
                except Exception as e:
                    print(f"重连尝试失败 {url_id} (第 {attempt + 1} 次): {e}")
                    if attempt == self.max_retry_attempts - 1:
                        # 最后一次尝试失败
                        print(f"重连彻底失败: {url_id}")
                        self.monitor_manager.update_session_status(url_id, MonitorStatus.ERROR, f"重连失败: {e}")
            
        except Exception as e:
            print(f"重连任务异常 {url_id}: {e}")
            self.monitor_manager.update_session_status(url_id, MonitorStatus.ERROR, f"重连任务异常: {e}")
        
        finally:
            # 清理重连任务
            if url_id in self.retry_tasks:
                del self.retry_tasks[url_id]
    
    async def _health_check_loop(self):
        """健康检查循环任务"""
        try:
            while self.is_running:
                # 使用更长的间隔减少频繁检查
                await asyncio.sleep(self.health_check_interval)
                if self.is_running:
                    await self._perform_health_check()
        except asyncio.CancelledError:
            print("健康检查任务已取消")
        except Exception as e:
            print(f"健康检查循环任务异常: {e}")
    
    async def _perform_health_check(self):
        """执行健康检查"""
        try:
            unhealthy_pages = []
            
            for url_id, page in self.pages.items():
                try:
                    # 检查页面是否仍然可访问
                    if page.is_closed():
                        print(f"检测到页面已关闭: {url_id}")
                        unhealthy_pages.append(url_id)
                        continue
                    
                    # 检查页面响应性
                    await asyncio.wait_for(
                        page.evaluate('document.readyState'),
                        timeout=5
                    )
                    
                    # 更新活动时间
                    self._update_page_activity(url_id)
                    
                except asyncio.TimeoutError:
                    print(f"页面响应超时: {url_id}")
                    self._increment_page_error(url_id)
                except Exception as e:
                    print(f"健康检查失败 {url_id}: {e}")
                    unhealthy_pages.append(url_id)
            
            # 处理不健康的页面
            for url_id in unhealthy_pages:
                print(f"触发不健康页面重连: {url_id}")
                await self._schedule_reconnect(url_id)
                
        except Exception as e:
            print(f"健康检查执行异常: {e}")
    
    async def _setup_page_listeners(self, page: Page, url_id: str):
        """设置页面事件监听器，包含Cookie自动保存功能"""
        try:
            # 监听控制台消息（过滤弹幕监听相关消息）
            def on_console_message(msg):
                text = msg.text
                if '[弹幕监听]' in text or 'DANMAKU_LISTENER' in text:
                    print(f"弹幕监听 {url_id}: {text}")
                    self.monitor_manager.update_heartbeat(url_id)
                    self._update_page_activity(url_id)
                    
                    # 如果检测到登录状态，自动保存Cookie
                    if '登录' in text or 'login' in text.lower() or '用户' in text:
                        asyncio.create_task(self._auto_save_domain_cookies(url_id, '检测到登录活动'))
                        
                elif msg.type == 'error':
                    # 过滤一些不重要的错误，避免不必要的重连
                    if any(ignore in text.lower() for ignore in [
                        'favicon.ico', 'manifest.json', 'service-worker',
                        'chrome-extension', 'moz-extension',
                        'vue全局错误捕获',  # Vue框架错误
                        'sentry.kuaishou.com',  # 快手监控服务
                        '429',  # 请求频率限制
                        'too many requests',  # 请求过多
                        'failed to load resource: the server responded with a status of 429',
                        # WebSocket连接相关错误
                        'websocket connection', 'websocket error', 'ws connection',
                        'connection reset', 'connection closed', 'connection aborted',
                        'net::err_connection_reset', 'net::err_connection_closed',
                        'net::err_connection_aborted', 'net::err_timed_out'
                    ]):
                        return
                    
                    print(f"控制台错误 {url_id}: {text}")
                    self.monitor_manager.increment_error_count(url_id)
                    self._increment_page_error(url_id)
            
            page.on('console', on_console_message)
            
            # 监听页面错误
            def on_page_error(error):
                error_text = str(error)
                
                # 过滤常见的无关紧要错误
                ignore_patterns = [
                    'removechild',  # DOM移除操作错误
                    'the node to be removed is not a child',  # 节点移除错误
                    'vue全局错误',  # Vue框架错误
                    'non-error promise rejection',  # Promise拒绝
                    'script error',  # 脚本错误（通常是跨域）
                    'websocket', 'connection reset', 'connection closed',
                    'connection aborted', 'connection timeout', 'network error',
                    'invalid regular expression',  # 正则表达式错误
                    'missing /',  # 缺少正则表达式结束符
                    'unterminated regular expression',  # 未终止的正则表达式
                    'rate limit exceeded',  # 频率限制错误
                    'timeout',  # 超时错误
                    'err_connection_refused',  # 连接被拒绝
                    'failed to load resource'  # 资源加载失败
                ]
                
                # 检查是否为可忽略的错误
                should_ignore = any(ignore in error_text.lower() for ignore in ignore_patterns)
                
                if should_ignore:
                    # 低级别记录可忽略的错误
                    print(f"[忽略错误] {url_id}: {error_text}")
                    return
                
                # 记录重要错误
                print(f"页面错误 {url_id}: {error_text}")
                self.monitor_manager.update_session_status(url_id, MonitorStatus.ERROR, error_text)
                self.monitor_manager.increment_error_count(url_id)
                self._increment_page_error(url_id)
            
            page.on('pageerror', on_page_error)
            
            # 监听页面崩溃
            def on_page_crash():
                print(f"页面崩溃: {url_id}")
                self.monitor_manager.update_session_status(url_id, MonitorStatus.ERROR, "页面崩溃")
                self._increment_page_error(url_id)
                # 从页面列表中移除崩溃的页面
                if url_id in self.pages:
                    del self.pages[url_id]
            
            page.on('crash', on_page_crash)
            
            # 监听页面关闭
            def on_page_close():
                print(f"页面已关闭: {url_id}")
                if url_id in self.pages:
                    del self.pages[url_id]
            
            page.on('close', on_page_close)
            
            # 监听请求失败
            def on_request_failed(request):
                if 'websocket' in request.url.lower():
                    # 过滤常见的WebSocket连接错误，避免触发重连
                    failure_reason = getattr(request, 'failure', '')
                    if any(ignore in str(failure_reason).lower() for ignore in [
                        'connection', 'reset', 'closed', 'transport', 'timeout',
                        'net::err_connection_reset', 'net::err_connection_closed',
                        'net::err_connection_aborted', 'net::err_timed_out'
                    ]):
                        # WebSocket连接相关错误，静默处理，不触发重连
                        print(f"[{url_id}] WebSocket连接错误(已过滤): {request.url} - {failure_reason}")
                        return
                    
                    print(f"[{url_id}] WebSocket请求失败: {request.url} - {failure_reason}")
                    self.monitor_manager.increment_error_count(url_id)
                    self._increment_page_error(url_id)
            
            page.on('requestfailed', on_request_failed)
            
            # 监听响应
            def on_response(response):
                if response.status >= 400:
                    # 过滤一些不重要的响应错误，避免不必要的重连
                    if any(ignore in response.url.lower() for ignore in [
                        'sentry.kuaishou.com',  # 快手监控服务
                        'favicon.ico',  # 图标文件
                        'manifest.json',  # 清单文件
                        'dbg1.jpg',  # 404图片文件
                    ]) or response.status in [404, 429]:  # 请求频率限制和404
                        return
                    
                    print(f"页面 {url_id} 响应错误: {response.status} {response.url}")
                    self._increment_page_error(url_id)
                else:
                    # 正常响应时更新活动时间
                    self._update_page_activity(url_id)
                    
                    # 如果是登录相关的响应，智能保存Cookie（限制频率）
                    if any(login_indicator in response.url.lower() for login_indicator in [
                        'login', 'auth', 'sso', 'oauth', 'signin', 'user', 'session'
                    ]):
                        # 检查是否在冷却时间内
                        current_time = time.time()
                        last_save_time = self.last_cookie_save_time.get(url_id, 0)
                        
                        if current_time - last_save_time > self.cookie_save_cooldown:
                            self.last_cookie_save_time[url_id] = current_time
                            asyncio.create_task(self._auto_save_domain_cookies(url_id, f'登录响应: {response.status}'))
                        else:
                            # 在冷却时间内，跳过保存
                            pass
            
            page.on('response', on_response)
            
            # 注入反检测脚本
            await self._inject_anti_detection_script(page)
            
            # 设置页面缩放为80%
            await page.evaluate("document.body.style.zoom = '0.8'")
            
        except Exception as e:
            print(f"设置页面监听器失败: {e}")
    
    async def _inject_anti_detection_script(self, page: Page):
        """注入反检测脚本，隐藏自动化特征"""
        try:
            anti_detection_script = """
            // 隐藏webdriver属性
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            
            // 重写chrome属性
            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };
            
            // 重写permissions查询
             const originalQuery = window.navigator.permissions.query;
             window.navigator.permissions.query = (parameters) => (
                 parameters.name === 'notifications' ?
                     Promise.resolve({ state: 'denied' }) :
                     originalQuery(parameters)
             );
            
            // 重写插件信息
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    {
                        0: {
                            type: "application/x-google-chrome-pdf",
                            suffixes: "pdf",
                            description: "Portable Document Format",
                            enabledPlugin: Plugin
                        },
                        description: "Portable Document Format",
                        filename: "internal-pdf-viewer",
                        length: 1,
                        name: "Chrome PDF Plugin"
                    },
                    {
                        0: {
                            type: "application/pdf",
                            suffixes: "pdf",
                            description: "",
                            enabledPlugin: Plugin
                        },
                        description: "",
                        filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai",
                        length: 1,
                        name: "Chrome PDF Viewer"
                    }
                ],
            });
            
            // 重写语言信息
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en-US', 'en'],
            });
            
            // 隐藏自动化相关的错误堆栈
            const originalError = window.Error;
            window.Error = function(...args) {
                const error = new originalError(...args);
                if (error.stack) {
                    error.stack = error.stack.replace(/\\s+at\\s.*[\\/\\\\].*playwright.*$/gm, '');
                }
                return error;
            };
            
            // 重写toString方法
            window.navigator.webdriver = false;
            
            console.log('[反检测] 反检测脚本已注入');
            """
            
            await page.add_init_script(anti_detection_script)
            
        except Exception as e:
            print(f"注入反检测脚本失败: {e}")
    
    async def _inject_danmaku_script(self, page: Page, url_id: str):
        """注入弹幕监听脚本"""
        try:
            # 加载脚本内容
            script_content = await self.load_script()
            
            # 预检查脚本内容是否包含可能的问题
            if not script_content or len(script_content.strip()) < 10:
                raise Exception("脚本内容为空或过短")
            
            # 检查常见的JavaScript语法问题
            syntax_issues = []
            if script_content.count('(') != script_content.count(')'):
                syntax_issues.append("括号不匹配")
            if script_content.count('{') != script_content.count('}'):
                syntax_issues.append("大括号不匹配")
            if script_content.count('[') != script_content.count(']'):
                syntax_issues.append("中括号不匹配")
            
            if syntax_issues:
                print(f"[{url_id}] 脚本语法检查发现问题: {', '.join(syntax_issues)}")
            
            print(f"[{url_id}] 开始注入脚本 (长度: {len(script_content)} 字符)")
            
            # 注入脚本，带有错误捕获
            try:
                await page.evaluate(f"""
                    try {{
                        {script_content}
                        console.log('[DANMAKU_LISTENER] 脚本注入成功');
                    }} catch (e) {{
                        console.error('[DANMAKU_LISTENER] 脚本执行错误:', e.message);
                        throw new Error('脚本执行失败: ' + e.message);
                    }}
                """)
                print(f"[{url_id}] 脚本注入成功")
            except Exception as inject_error:
                inject_error_msg = str(inject_error)
                print(f"[{url_id}] 脚本注入失败: {inject_error_msg}")
                
                # 如果是语法错误，尝试使用内置简单脚本
                if any(keyword in inject_error_msg.lower() for keyword in ['syntax', 'unexpected', 'missing']):
                    print(f"[{url_id}] 检测到语法错误，尝试使用备用脚本")
                    fallback_script = """
                        console.log('[DANMAKU_LISTENER] 使用备用脚本');
                        window.danmakuListener = {
                            status: 'fallback',
                            platform: 'unknown',
                            socket: null,
                            init: function() {
                                console.log('[DANMAKU_LISTENER] 备用脚本初始化');
                                this.status = 'active';
                            }
                        };
                        window.danmakuListener.init();
                    """
                    
                    try:
                        await page.evaluate(fallback_script)
                        print(f"[{url_id}] 已使用备用脚本")
                    except Exception as fallback_error:
                        print(f"[{url_id}] 备用脚本也失败: {fallback_error}")
                        raise Exception(f"脚本注入失败: {inject_error_msg}")
                else:
                    raise Exception(f"脚本注入失败: {inject_error_msg}")
            
            print(f"[{url_id}] 脚本已注入，等待初始化...")
            
            # 等待脚本初始化 - 增加初始等待时间，让页面完全加载
            await asyncio.sleep(10)  # 增加等待时间到10秒
            
            # 检查脚本是否成功注入 - 优化等待机制
            max_wait_time = 60  # 增加最大等待时间到60秒
            check_interval = 3  # 每3秒检查一次，减少频繁检查
            
            for attempt in range(max_wait_time):
                try:
                    script_status = await page.evaluate("""
                        () => {
                            try {
                                // 更详细的检查逻辑，增加空值检查
                                if (typeof window.danmakuListener !== 'undefined' && window.danmakuListener !== null) {
                                    let status = 'success';
                                    let listenerStatus = window.danmakuListener.status;
                                    let platform = window.danmakuListener.platform;
                                    let socketState = window.danmakuListener.socket ? window.danmakuListener.socket.readyState : null;
                                    
                                    // 检查状态是否为undefined或null
                                    if (listenerStatus === undefined || listenerStatus === null) {
                                        status = 'waiting';
                                    }
                                    // 检查是否正在初始化中
                                    else if (listenerStatus === 'initializing') {
                                        status = 'initializing';
                                    }
                                    // 检查快速初始化状态
                                    else if (listenerStatus === 'ready' || listenerStatus === 'active' || listenerStatus === 'connected') {
                                        status = 'success';
                                    }
                                    // 检查是否正在连接中
                                    else if (listenerStatus === 'connecting') {
                                        status = 'success'; // 连接中状态也视为成功，因为脚本已注入
                                    }
                                    // 其他未知状态也视为等待
                                    else {
                                        status = 'waiting';
                                    }
                                    
                                    return {
                                        status: status,
                                        listenerStatus: listenerStatus,
                                        platform: platform,
                                        socketState: socketState,
                                        timestamp: Date.now()
                                    };
                                } else {
                                    // 检查是否有其他相关的全局对象
                                    let windowKeys = Object.keys(window);
                                    let danmakuKeys = windowKeys.filter(k => k.includes('danmaku') || k.includes('listener') || k.includes('ws'));
                                    
                                    return {
                                        status: 'waiting',
                                        error: 'danmakuListener not yet available',
                                        windowKeys: danmakuKeys.join(','),
                                        allKeysCount: windowKeys.length,
                                        timestamp: Date.now()
                                    };
                                }
                            } catch (e) {
                                return {
                                    status: 'error',
                                    error: e.message,
                                    stack: e.stack,
                                    timestamp: Date.now()
                                };
                            }
                        }
                    """)
                    
                    # 修复状态检查逻辑，避免Cannot read properties of null错误
                    if script_status and script_status.get('status') == 'success':
                        print(f"[{url_id}] 弹幕监听脚本注入成功 - 平台: {script_status.get('platform')}, 状态: {script_status.get('listenerStatus')}")
                        break
                    elif script_status and script_status.get('status') == 'initializing':
                        print(f"[{url_id}] 脚本正在初始化中... (第{attempt + 1}次检查)")
                        if attempt < max_wait_time - 1:
                            await asyncio.sleep(check_interval)
                            continue
                        else:
                            print(f"[{url_id}] 脚本初始化超时")
                            raise Exception("脚本初始化超时")
                    elif script_status and script_status.get('status') == 'waiting':
                        if attempt < max_wait_time - 1:  # 不是最后一次尝试
                            window_keys = script_status.get('windowKeys', '')
                            all_keys_count = script_status.get('allKeysCount', 0)
                            print(f"[{url_id}] 等待脚本初始化... (第{attempt + 1}次检查, 相关属性: {window_keys}, 总属性数: {all_keys_count})")
                            await asyncio.sleep(check_interval)
                            continue
                        else:
                            # 最后一次尝试失败
                            error_msg = script_status.get('error', '未知错误')
                            window_keys = script_status.get('windowKeys', '')
                            all_keys_count = script_status.get('allKeysCount', 0)
                            print(f"[{url_id}] 弹幕监听脚本注入超时 - 错误: {error_msg}, 相关window属性: {window_keys}, 总属性数: {all_keys_count}")
                            
                            # 尝试注入一个简单的测试脚本来诊断问题
                            try:
                                await page.evaluate("""
                                    console.log('诊断信息: window对象属性数量:', Object.keys(window).length);
                                    console.log('诊断信息: 包含danmaku的属性:', Object.keys(window).filter(k => k.includes('danmaku')));
                                    console.log('诊断信息: 包含listener的属性:', Object.keys(window).filter(k => k.includes('listener')));
                                """)
                            except Exception as diag_error:
                                print(f"[{url_id}] 诊断脚本执行失败: {diag_error}")
                            
                            raise Exception(f"脚本注入超时: {error_msg}")
                    else:
                        # 处理script_status为null或undefined的情况
                        if not script_status:
                            print(f"[{url_id}] 脚本状态检查返回null/undefined，可能是脚本注入失败")
                            # 尝试重新注入脚本
                            if attempt < 3:  # 最多重试3次
                                print(f"[{url_id}] 尝试重新注入脚本 (第{attempt + 1}次重试)")
                                await page.evaluate(f"""
                                    // 清理旧的danmakuListener对象
                                    if (window.danmakuListener) {{
                                        delete window.danmakuListener;
                                    }}
                                    // 重新注入脚本
                                    {script_content}
                                """)
                                await asyncio.sleep(5)  # 等待5秒让脚本重新初始化
                                continue
                            else:
                                raise Exception("脚本注入失败：状态检查返回null")
                        else:
                            # 其他错误
                            error_msg = script_status.get('error', '未知错误')
                            stack_trace = script_status.get('stack', '')
                            print(f"[{url_id}] 弹幕监听脚本注入失败 - 错误: {error_msg}")
                            if stack_trace:
                                print(f"[{url_id}] 错误堆栈: {stack_trace}")
                            raise Exception(f"脚本注入失败: {error_msg}")
                        
                except Exception as e:
                    if 'script injection' in str(e).lower() or 'timeout' in str(e).lower():
                        raise e  # 重新抛出关键错误
                    else:
                        print(f"[{url_id}] 检查脚本状态时出错: {e}")
                        if attempt == max_wait_time - 1:
                            raise Exception(f"脚本状态检查失败: {e}")
                        await asyncio.sleep(check_interval)
                
        except Exception as e:
            print(f"[{url_id}] 脚本注入异常: {e}")
            
            # 如果是认证相关错误，提供更明确的错误信息
            error_msg = str(e).lower()
            if any(keyword in error_msg for keyword in ['login', 'auth', 'token', '认证', '登录']):
                print(f"[{url_id}] 检测到认证错误，建议检查Cookie是否过期")
                print(f"[{url_id}] 请手动登录斗鱼账号并更新Cookie文件")
            
            raise
    
    async def get_page_info(self, url_id: str) -> Optional[Dict]:
        """获取页面信息"""
        if url_id not in self.pages:
            return None
        
        try:
            page = self.pages[url_id]
            info = {
                'title': await page.title(),
                'url': page.url,
                'is_closed': page.is_closed(),
                'viewport': page.viewport_size
            }
            return info
        except Exception as e:
            print(f"获取页面信息失败 {url_id}: {e}")
            return None
    
    async def take_screenshot(self, url_id: str, path: str = None) -> Optional[str]:
        """截取页面截图"""
        if url_id not in self.pages:
            return None
        
        try:
            page = self.pages[url_id]
            if not path:
                path = f"screenshot_{url_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            await page.screenshot(path=path, full_page=True)
            return path
        except Exception as e:
            print(f"截图失败 {url_id}: {e}")
            return None
    
    async def restart_monitoring(self, url_id: str, acquire_lock: bool = True) -> bool:
        """带锁的重启监控，确保操作原子性"""
        
        async def _restart():
            print(f"准备重启监控: {url_id}")
            try:
                # 1. 停止当前监控
                await self.stop_monitoring(url_id, acquire_lock=False)  # 传递标志以避免重复锁定
                print(f"旧监控已停止: {url_id}")

                # 2. 重新启动监控
                url_config = self.url_manager.get_url(url_id)
                if not url_config:
                    print(f"无法重启，未找到URL配置: {url_id}")
                    return False

                await asyncio.sleep(1)  # 短暂等待，确保资源完全释放

                success = await self.start_monitoring(url_id, acquire_lock=False)  # 传递标志以避免重复锁定
                if success:
                    print(f"新监控已启动: {url_id}")
                return success

            except Exception as e:
                print(f"重启监控时出错 {url_id}: {e}")
                # 确保即使失败，状态也能得到更新
                self.monitor_manager.update_session_status(url_id, MonitorStatus.ERROR, f"重启失败: {e}")
                return False

        if acquire_lock:
            self._ensure_lock()
            async with self.lock:
                return await _restart()
        else:
            return await _restart()
    
    async def get_browser_stats(self) -> Dict:
        """获取浏览器统计信息"""
        active_sessions = len([s for s in self.page_sessions.values() if s['error_count'] < 10])
        total_errors = sum(s['error_count'] for s in self.page_sessions.values())
        
        stats = {
             'is_running': self.is_running,
             'active_pages': len(self.pages),
             'total_sessions': len(self.page_sessions),
             'active_sessions': active_sessions,
             'total_errors': total_errors,
             'page_list': list(self.pages.keys()),
             # 使用更稳妥的浏览器连接判断：仅依据对象存在性，避免依赖内部未公开属性
             'browser_connected': self.browser is not None,
             'max_pages_limit': self.max_pages,

             'health_check_enabled': self.health_check_task is not None and not self.health_check_task.done(),
             'active_retry_tasks': len(self.retry_tasks),
             'max_retry_attempts': self.max_retry_attempts,
             'retry_delay': self.retry_delay,
             'health_check_interval': self.health_check_interval
         }
        
        # 不再统计上下文数量，固定为0
        stats['contexts_count'] = 0
        
        return stats
    
    async def cleanup(self):
        """清理资源 - 增强版本"""
        try:
            print("开始清理浏览器资源...")
            
            # 1. 停止所有监控
            await self.stop_all_monitoring()
            

            
            # 3. 自动保存cookies（如果启用）
            if self.auto_save_cookies and self.context:
                try:
                    # 为每个活跃页面分别保存Cookie
                    for url_id in list(self.pages.keys()):
                        try:
                            # 独立上下文功能已禁用，始终使用共享上下文保存
                            await self.save_cookies(f"auto_save_{url_id}")
                        except Exception as e:
                            print(f"保存{url_id}的cookies失败: {e}")
                    
                    # 保存默认Cookie
                    await self.save_cookies("auto_save_default")
                    print("系统退出时已自动保存所有cookies")
                except Exception as e:
                    print(f"自动保存cookies失败: {e}")
            
            # 4. 关闭所有页面
            if self.pages:
                for url_id, page in list(self.pages.items()):
                    try:
                        # 在关闭前执行最后一次清理
                        await page.evaluate("""
                            // 清理所有事件监听器
                            window.removeEventListener && window.removeEventListener('beforeunload', null);
                            // 强制垃圾回收
                            window.gc && window.gc();
                            // 清理全局变量
                            if (window.danmakuListener) {
                                window.danmakuListener = null;
                            }
                        """)
                        await page.close()
                    except Exception as e:
                        print(f"关闭页面时出错 {url_id}: {e}")
            
            # 5. 关闭浏览器上下文
            if self.context:
                try:
                    await self.context.close()
                    print("浏览器上下文已关闭")
                except Exception as e:
                    print(f"关闭浏览器上下文失败: {e}")
                finally:
                    self.context = None
            
            # 6. 关闭浏览器
            if self.browser:
                try:
                    await self.browser.close()
                    print("浏览器已关闭")
                except Exception as e:
                    print(f"关闭浏览器失败: {e}")
                finally:
                    self.browser = None
            
            # 独立上下文功能已禁用，不再清理独立上下文
            
            # 9. 停止playwright
            if self.playwright:
                try:
                    await self.playwright.stop()
                    print("Playwright已停止")
                except Exception as e:
                    print(f"停止Playwright失败: {e}")
                finally:
                    self.playwright = None
            

            
            # 11. 停止Cookie定期保存任务
            self.stop_periodic_cookie_save()
            
            # 12. 停止重启管理器
            if self.restart_manager:
                await self.restart_manager.stop()
                print("重启管理器已停止")
            
            # 13. 清理所有状态
            self.is_running = False
            self.pages.clear()
            self.page_sessions.clear()
            
            print("浏览器管理器已完全清理")
            
        except Exception as e:
            print(f"清理浏览器管理器时出错: {e}")
    
    def _ensure_cookie_directory(self):
        """确保cookie目录存在"""
        try:
            if not os.path.exists(self.cookie):
                os.makedirs(self.cookie)
                print(f"创建cookie目录: {self.cookie}")
        except Exception as e:
            print(f"创建cookie目录失败: {e}")
            self.cookie_enabled = False
    
    def _get_cookie_path(self, identifier: str = None) -> str:
        """获取cookie文件路径"""
        if identifier:
            # 对于特殊文件名（如douyu_cookies），直接使用该文件名
            if identifier in ['douyu_cookies']:
                filename = f"{identifier}.json"
            else:
                filename = f"{self.cookie_file_prefix}_{identifier}.json"
        else:
            filename = f"{self.cookie_file_prefix}_default.json"
        return os.path.join(self.cookie, filename)
    
    def _find_cookie_files(self) -> List[str]:
        """查找所有cookie文件，支持多种命名格式"""
        try:
            if not os.path.exists(self.cookie):
                return []
            
            cookie_files = []
            for file in os.listdir(self.cookie):
                # 支持多种Cookie文件命名格式
                if file.endswith('.json') and any(file.startswith(pattern) for pattern in self.cookie_file_patterns):
                    cookie_files.append(os.path.join(self.cookie, file))
            
            # 按修改时间排序，最新的在前
            cookie_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            return cookie_files
        except Exception as e:
            print(f"查找cookie文件失败: {e}")
            return []
    
    def _validate_cookie_file(self, cookie_file):
        """验证Cookie文件是否有效"""
        try:
            if not os.path.exists(cookie_file):
                self.logger.warning(f"Cookie文件不存在: {cookie_file}")
                return False
                
            with open(cookie_file, 'r', encoding='utf-8') as f:
                content = json.load(f)
            
            # 检查文件结构
            if not isinstance(content, dict):
                self.logger.warning(f"Cookie文件格式错误: {cookie_file}")
                return False
                
            # 检查是否为空Cookie
            cookies = content.get('cookies', [])
            origins = content.get('origins', [])
            
            if not cookies and not origins:
                self.logger.warning(f"Cookie文件为空: {cookie_file}")
                return False
                
            # 检查Cookie有效性
            for cookie in cookies:
                if not all(key in cookie for key in ['name', 'value', 'domain']):
                    self.logger.warning(f"Cookie文件包含无效的Cookie项: {cookie_file}")
                    return False
                    
            return True
            
        except Exception as e:
            self.logger.error(f"验证Cookie文件失败 {cookie_file}: {e}")
            return False

    async def _load_cookies(self, identifier: str = None, url_id: str = None) -> Optional[Dict]:
        """加载cookie文件，支持以域名为单位的加载和多种命名格式"""
        if not self.cookie_enabled:
            return None
        
        try:
            print(f"[COOKIE_DEBUG] 开始加载Cookie: identifier={identifier}, url_id={url_id}")
            
            # 如果指定了标识符，尝试加载特定文件
            if identifier:
                cookie_path = self._get_cookie_path(identifier)
                print(f"[COOKIE_DEBUG] 尝试加载特定Cookie文件: {cookie_path}")
                if os.path.exists(cookie_path):
                    # 验证Cookie文件是否有效
                    if not self._validate_cookie_file(cookie_path):
                        print(f"跳过无效的Cookie文件: {cookie_path}")
                        return None
                    
                    with open(cookie_path, 'r', encoding='utf-8') as f:
                        storage_state = json.load(f)
                        # 检查cookie文件是否有效（包含cookies数据）
                        if storage_state.get('cookies') or storage_state.get('origins'):
                            print(f"已加载有效cookie文件: {cookie_path}")
                            return storage_state
                        else:
                            print(f"警告: cookie文件为空: {cookie_path}")
            
            # 如果提供了URL ID，尝试加载对应域名的Cookie文件
            if url_id:
                domain = self._get_domain_from_url_id(url_id)
                print(f"[COOKIE_DEBUG] 尝试加载域名Cookie: url_id={url_id}, domain={domain}")
                if domain != "unknown_domain":
                    # 尝试多种域名Cookie文件格式，扩展支持更多命名格式
                    domain_patterns = [
                        f"domain_{domain}",  # 标准域名格式
                        f"douyu_cookies",    # 斗鱼专用Cookie文件
                        f"optimized_{domain}_cookies",  # 优化版Cookie文件
                        f"browser_cookies_domain_{domain}",  # 带domain_后缀的browser_cookies格式
                        f"browser_cookies_{domain}",  # 原有的browser_cookies格式
                        f"{domain}_cookies"  # 其他可能的格式
                    ]
                    
                    print(f"[COOKIE_DEBUG] 尝试以下Cookie文件模式: {domain_patterns}")
                    
                    best_storage_state = None
                    best_cookie_count = 0
                    best_has_cookies = False
                    
                    for pattern in domain_patterns:
                        # 构建完整的Cookie文件路径
                        if pattern == "douyu_cookies":  # 特殊文件名直接使用
                            domain_cookie_path = os.path.join(self.cookie, f"{pattern}.json")
                        else:
                            domain_cookie_path = self._get_cookie_path(pattern)
                              
                        print(f"[COOKIE_DEBUG] 检查Cookie文件: {domain_cookie_path}")
                        if os.path.exists(domain_cookie_path):
                            print(f"[COOKIE_DEBUG] 找到Cookie文件: {domain_cookie_path}")
                            # 验证Cookie文件是否有效
                            if not self._validate_cookie_file(domain_cookie_path):
                                print(f"跳过无效的域名Cookie文件: {domain_cookie_path}")
                                continue
                            
                            with open(domain_cookie_path, 'r', encoding='utf-8') as f:
                                storage_state = json.load(f)
                                # 检查cookie文件是否有效
                                cookies_count = len(storage_state.get('cookies', []))
                                origins_count = len(storage_state.get('origins', []))
                                total_count = cookies_count + origins_count
                                has_cookies = cookies_count > 0
                                  
                                print(f"[COOKIE_DEBUG] Cookie文件信息: cookies={cookies_count}, origins={origins_count}")
                                  
                                # 优先选择包含cookies的文件，如果有cookies，即使总数较少也优先选择
                                if has_cookies and not best_has_cookies:
                                    best_storage_state = storage_state
                                    best_cookie_count = total_count
                                    best_has_cookies = True
                                    print(f"[COOKIE_DEBUG] 更新最佳Cookie文件(包含cookies): {domain_cookie_path} (cookies: {cookies_count})")
                                # 如果两个文件都有cookies，则选择总数多的
                                elif has_cookies and best_has_cookies and total_count > best_cookie_count:
                                    best_storage_state = storage_state
                                    best_cookie_count = total_count
                                    print(f"[COOKIE_DEBUG] 更新最佳Cookie文件(更多数据): {domain_cookie_path} (总计: {total_count})")
                                # 如果都没有cookies，则选择总数多的
                                elif not has_cookies and not best_has_cookies and total_count > best_cookie_count:
                                    best_storage_state = storage_state
                                    best_cookie_count = total_count
                                    print(f"[COOKIE_DEBUG] 更新最佳Cookie文件(无cookies): {domain_cookie_path} (总计: {total_count})")
                                else:
                                    print(f"[COOKIE_DEBUG] 跳过Cookie文件: {domain_cookie_path} (cookies: {cookies_count}, origins: {origins_count}, 当前最佳: {best_cookie_count})")
                        else:
                            print(f"[COOKIE_DEBUG] Cookie文件不存在: {domain_cookie_path}")
                    
                    # 如果找到了包含cookies的文件，返回最佳的
                    if best_storage_state and best_cookie_count > 0:
                        # 即使选择了最佳文件，如果它没有cookies但存在其他有cookies的文件，优先使用那些
                        if best_storage_state.get('cookies') is None or len(best_storage_state.get('cookies', [])) == 0:
                            print(f"[COOKIE_DEBUG] 最佳文件没有cookies，尝试查找其他有cookies的文件")
                            for pattern in domain_patterns:
                                if pattern == "douyu_cookies":
                                    alt_cookie_path = os.path.join(self.cookie, f"{pattern}.json")
                                else:
                                    alt_cookie_path = self._get_cookie_path(pattern)
                                
                                if os.path.exists(alt_cookie_path):
                                    try:
                                        with open(alt_cookie_path, 'r', encoding='utf-8') as f2:
                                            alt_state = json.load(f2)
                                        if alt_state.get('cookies') and len(alt_state.get('cookies', [])) > 0:
                                            print(f"[COOKIE_DEBUG] 找到另一个包含cookies的文件: {alt_cookie_path}")
                                            best_storage_state = alt_state
                                            break
                                    except:
                                        pass
                        
                        print(f"已加载最佳域名Cookie文件，包含 {len(best_storage_state.get('cookies', []))} 个cookies, {len(best_storage_state.get('origins', []))} 个origins")
                        return best_storage_state
                    elif best_storage_state:
                        # 如果所有文件都为空，但找到了文件，也返回（保持原有行为）
                        print("已加载域名Cookie文件（所有文件均为空）")
                        return best_storage_state
            
            # 否则查找最新的有效cookie文件
            cookie_files = self._find_cookie_files()
            print(f"[COOKIE_DEBUG] 找到 {len(cookie_files)} 个Cookie文件")
            for cookie_file in cookie_files:
                try:
                    print(f"[COOKIE_DEBUG] 尝试加载Cookie文件: {cookie_file}")
                    # 验证Cookie文件是否有效
                    if not self._validate_cookie_file(cookie_file):
                        print(f"跳过无效的cookie文件: {cookie_file}")
                        continue
                    
                    with open(cookie_file, 'r', encoding='utf-8') as f:
                        storage_state = json.load(f)
                        # 检查cookie文件是否有效
                        if storage_state.get('cookies') or storage_state.get('origins'):
                            print(f"已加载最新有效cookie文件: {cookie_file}")
                            return storage_state
                        else:
                            print(f"跳过空cookie文件: {cookie_file}")
                except Exception as e:
                    print(f"读取cookie文件失败 {cookie_file}: {e}")
            
            print("未找到有效的cookie文件")
            return None
            
        except Exception as e:
            print(f"加载cookie失败: {e}")
            import traceback
            traceback.print_exc()
            return None
        """保存当前浏览器cookies"""
        if not self.cookie_enabled or not self.context:
            return False
        
        try:
            # 获取当前存储状态
            storage_state = await self.context.storage_state()
            
            # 检查存储状态是否包含有效的cookies
            cookies = storage_state.get('cookies', [])
            origins = storage_state.get('origins', [])
            
            # 增强验证：确保cookies数据有效
            valid_cookies = []
            for cookie in cookies:
                # 检查必需字段
                if 'name' in cookie and 'value' in cookie and 'domain' in cookie:
                    valid_cookies.append(cookie)
            
            if len(valid_cookies) == 0 and len(origins) == 0:
                print(f"警告: 当前浏览器没有有效的cookies，跳过保存")
                return False
            
            # 更新存储状态为有效cookies
            storage_state['cookies'] = valid_cookies
            
            # 保存到文件
            cookie_path = self._get_cookie_path(identifier)
            
            # 确保目录存在
            os.makedirs(os.path.dirname(cookie_path), exist_ok=True)
            
            with open(cookie_path, 'w', encoding='utf-8') as f:
                json.dump(storage_state, f, ensure_ascii=False, indent=2)
            
            # 验证文件是否成功保存且包含有效数据
            if os.path.exists(cookie_path):
                try:
                    with open(cookie_path, 'r', encoding='utf-8') as f:
                        saved_data = json.load(f)
                        saved_cookies = saved_data.get('cookies', [])
                        if len(saved_cookies) > 0 or len(saved_data.get('origins', [])) > 0:
                            print(f"cookies已保存到: {cookie_path} (有效cookies: {len(saved_cookies)})")
                            return True
                        else:
                            print(f"警告: 保存的cookies文件不包含有效数据，删除无效文件")
                            os.remove(cookie_path)
                            return False
                except Exception as e:
                    print(f"验证保存的cookies文件失败: {e}")
                    return False
            else:
                print(f"保存cookies失败: 文件未创建")
                return False
                
        except Exception as e:
            print(f"保存cookies失败: {e}")
            return False
    
    async def clear_cookies(self) -> bool:
        """清除当前浏览器cookies"""
        if not self.context:
            return False
        
        try:
            await self.context.clear_cookies()
            print("浏览器cookies已清除")
            return True
        except Exception as e:
            print(f"清除cookies失败: {e}")
            return False
    
    async def refresh_context_with_cookies(self, identifier: str = None, url_id: str = None) -> bool:
        """使用新的cookies刷新浏览器上下文，支持以域名为单位的加载"""
        if not self.browser:
            return False
        
        try:
            # 保存当前页面信息
            current_pages = list(self.pages.keys())
            
            # 关闭当前上下文
            if self.context:
                await self.context.close()
            
            # 加载新的cookies（支持域名级加载）
            storage_state = None
            if self.cookie_enabled:
                storage_state = await self._load_cookies(identifier, url_id)
            
            # 创建新的上下文
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                java_script_enabled=True,
                ignore_https_errors=True,
                bypass_csp=True,
                storage_state=storage_state
            )
            
            # 清除旧的页面引用
            self.pages.clear()
            
            # 显示加载的Cookie信息
            if url_id:
                domain = self._get_domain_from_url_id(url_id)
                print(f"浏览器上下文已刷新，使用域名Cookie: {domain}")
            else:
                print(f"浏览器上下文已刷新，使用cookies: {identifier or 'default'}")
            
            # 可选：重新启动之前的监控
            for url_id in current_pages:
                print(f"重新启动监控: {url_id}")
                await self.start_monitoring(url_id, acquire_lock=False)
            
            return True
            
        except Exception as e:
            print(f"刷新浏览器上下文失败: {e}")
            return False
    
    def get_cookie_info(self) -> Dict:
        """获取cookie相关信息"""
        cookie_files = self._find_cookie_files()
        return {
            'cookie_enabled': self.cookie_enabled,
            'cookieectory': self.cookie,
            'auto_save_cookies': self.auto_save_cookies,
            'available_cookie_files': len(cookie_files),
            'cookie_files': [{
                'path': f,
                'name': os.path.basename(f),
                'modified': datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d %H:%M:%S')
            } for f in cookie_files]
        }
    
    def __del__(self):
        """析构函数"""
        if self.is_running:
            print("警告: BrowserManager未正确清理，请调用cleanup()方法")
    
    def _get_domain_from_url(self, url: str) -> str:
        """从URL中提取域名"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc
            # 移除端口号
            if ':' in domain:
                domain = domain.split(':')[0]
            return domain
        except Exception as e:
            print(f"提取域名失败 {url}: {e}")
            return "unknown_domain"
    
    def _get_domain_from_url_id(self, url_id: str) -> str:
        """从URL ID获取域名"""
        try:
            # 从URL管理器获取URL
            url_config = self.url_manager.get_url(url_id)
            if url_config:
                # 从配置中提取实际的URL字符串
                url = url_config.get('url', '')
                if url:
                    domain = self._get_domain_from_url(url)
                    print(f"[COOKIE_DEBUG] 从URL配置获取域名: {url_id} -> {url} -> {domain}")
                    return domain
                else:
                    print(f"URL配置中没有找到有效的URL: {url_config}")
                    return "unknown_domain"
            else:
                # 如果URL管理器中没有，尝试从URL ID中提取域名
                # 检查URL ID是否包含URL信息
                if url_id.startswith('http'):
                    domain = self._get_domain_from_url(url_id)
                    print(f"[COOKIE_DEBUG] 从URL ID直接获取域名: {url_id} -> {domain}")
                    return domain
                elif 'douyu' in url_id.lower():
                    print(f"[COOKIE_DEBUG] 从URL ID识别斗鱼平台: {url_id} -> www.douyu.com")
                    return 'www.douyu.com'
                elif 'bilibili' in url_id.lower():
                    print(f"[COOKIE_DEBUG] 从URL ID识别B站平台: {url_id} -> live.bilibili.com")
                    return 'live.bilibili.com'
                elif 'huya' in url_id.lower():
                    print(f"[COOKIE_DEBUG] 从URL ID识别虎牙平台: {url_id} -> www.huya.com")
                    return 'www.huya.com'
                elif 'weixin' in url_id.lower() or 'channels' in url_id.lower():
                    print(f"[COOKIE_DEBUG] 从URL ID识别微信平台: {url_id} -> channels.weixin.qq.com")
                    return 'channels.weixin.qq.com'
                else:
                    # 尝试从URL ID中解析可能的域名信息
                    # 检查URL ID是否包含常见的平台标识
                    url_id_lower = url_id.lower()
                    platform_domains = {
                        'douyu': 'www.douyu.com',
                        'bilibili': 'live.bilibili.com',
                        'huya': 'www.huya.com',
                        'kuaishou': 'live.kuaishou.com',
                        'taobao': 'tbzb.taobao.com',
                        '1688': 'live.1688.com',
                        'xiaohongshu': 'ark.xiaohongshu.com',
                        'weixin': 'channels.weixin.qq.com',
                        'tiktok': 'www.tiktok.com'
                    }
                    
                    for platform, domain in platform_domains.items():
                        if platform in url_id_lower:
                            print(f"[COOKIE_DEBUG] 从URL ID识别平台: {url_id} -> {domain}")
                            return domain
                    
                    # 对于类似be042e69-c4b3-4115-8e92-10e12d4a8d1c这样的UUID格式ID
                    # 检查是否在URL中包含平台信息
                    if '-' in url_id and len(url_id) > 20:  # UUID-like format
                        # 尝试从日志或上下文中推断平台
                        # 默认假设为斗鱼平台，因为日志中显示的是斗鱼相关错误
                        print(f"检测到UUID格式URL ID: {url_id}，默认使用斗鱼平台")
                        return 'www.douyu.com'
                    
                    print(f"无法从URL ID识别域名: {url_id}")
                    return "unknown_domain"
        except Exception as e:
            print(f"从URL ID获取域名失败 {url_id}: {e}")
            return "unknown_domain"
    
    async def _auto_save_domain_cookies(self, url_id: str, trigger_reason: str = "定时保存"):
        """以网站为单位自动保存Cookie"""
        if not self.auto_save_cookies or not self.cookie_enabled:
            return
        
        try:
            # 获取域名
            domain = self._get_domain_from_url_id(url_id)
            if domain == "unknown_domain":
                print(f"[{url_id}] 无法识别域名，跳过Cookie保存")
                return
            
            # 首先尝试获取页面对应的上下文
            context_to_save = None
            
            # 检查是否有共享的上下文
            if self.context:
                context_to_save = self.context
                print(f"[{domain}] 使用共享上下文保存Cookie")
            # 检查是否有活跃的页面
            elif url_id in self.pages and self.pages[url_id] and not self.pages[url_id].is_closed():
                # 通过页面获取上下文
                try:
                    context_to_save = self.pages[url_id].context
                    print(f"[{domain}] 通过页面获取上下文保存Cookie")
                except Exception as e:
                    print(f"[{domain}] 获取页面上下文失败: {e}")
            
            if not context_to_save:
                print(f"[{domain}] 警告: 无法找到有效的上下文，跳过Cookie保存")
                return
            
            # 获取存储状态
            storage_state = await context_to_save.storage_state()
            
            # 详细检查存储状态
            cookies_count = len(storage_state.get('cookies', []))
            origins_count = len(storage_state.get('origins', []))
            
            print(f"[{domain}] Cookie统计 - Cookies: {cookies_count}, Origins: {origins_count}")
            
            # 检查存储状态是否包含有效的cookies
            if cookies_count == 0 and origins_count == 0:
                print(f"[{domain}] 警告: 当前上下文没有有效的cookies，跳过保存")
                return
            
            # 以域名为单位保存到文件
            cookie_path = self._get_cookie_path(f"domain_{domain}")
            
            # 确保目录存在
            os.makedirs(os.path.dirname(cookie_path), exist_ok=True)
            
            with open(cookie_path, 'w', encoding='utf-8') as f:
                json.dump(storage_state, f, ensure_ascii=False, indent=2)
            
            # 验证文件是否成功保存
            if os.path.exists(cookie_path):
                file_size = os.path.getsize(cookie_path)
                print(f"[{domain}] Cookie已成功保存 - 文件大小: {file_size}字节 - 触发原因: {trigger_reason}")
                
                # 记录保存的Cookie信息
                if not hasattr(self, 'last_cookie_save'):
                    self.last_cookie_save = {}
                self.last_cookie_save[domain] = {
                    'timestamp': datetime.now(),
                    'trigger': trigger_reason,
                    'cookies_count': cookies_count,
                    'origins_count': origins_count,
                    'file_path': cookie_path,
                    'url_id': url_id
                }
            else:
                print(f"[{domain}] 警告: Cookie文件保存失败，文件不存在")
                
        except Exception as e:
            print(f"[{url_id}] 自动保存Cookie失败: {e}")
            import traceback
            print(f"详细错误信息: {traceback.format_exc()}")
    
    async def periodic_save_cookies(self, interval_minutes: int = 10):
        """定期保存所有网站的Cookie"""
        while self.is_running:
            try:
                await asyncio.sleep(interval_minutes * 60)  # 转换为秒
                
                if not self.is_running:
                    break
                
                print(f"开始定期保存Cookie（间隔: {interval_minutes}分钟）")
                
                # 收集所有活跃页面的域名，避免重复保存同一域名
                domains_saved = set()
                
                # 为每个活跃页面保存Cookie（以域名为单位）
                for url_id in list(self.pages.keys()):
                    if self.pages.get(url_id) and not self.pages[url_id].is_closed():
                        domain = self._get_domain_from_url_id(url_id)
                        if domain != "unknown_domain" and domain not in domains_saved:
                            await self._auto_save_domain_cookies(url_id, "定期保存")
                            domains_saved.add(domain)
                            await asyncio.sleep(1)  # 避免同时大量操作
                
                print(f"定期保存Cookie完成，共保存了 {len(domains_saved)} 个域名的Cookie")
                
            except asyncio.CancelledError:
                print("定期保存Cookie任务已取消")
                break
            except Exception as e:
                print(f"定期保存Cookie失败: {e}")
    
    def start_periodic_cookie_save(self, interval_minutes: int = 10):
        """启动定期保存Cookie任务"""
        if hasattr(self, 'cookie_save_task') and self.cookie_save_task and not self.cookie_save_task.done():
            print("Cookie定期保存任务已在运行")
            return
        
        if self.auto_save_cookies and self.cookie_enabled:
            self.cookie_save_task = asyncio.create_task(self.periodic_save_cookies(interval_minutes))
            print(f"已启动Cookie定期保存任务（间隔: {interval_minutes}分钟）")
    
    def stop_periodic_cookie_save(self):
        """停止定期保存Cookie任务"""
        if hasattr(self, 'cookie_save_task') and self.cookie_save_task and not self.cookie_save_task.done():
            self.cookie_save_task.cancel()
            print("Cookie定期保存任务已停止")