"""
Chromium重启管理器
用于解决Chromium注入脚本监听方式的内存泄漏问题
通过定时重启Chromium进程来确保系统稳定运行
"""

import asyncio
import time
import logging
from typing import Dict, Optional, Any, List
from datetime import datetime, timedelta
import json
import os
from dataclasses import dataclass, asdict

@dataclass
class RestartState:
    """重启状态数据类"""
    url_id: str
    url: str
    script_name: str
    cookies_data: Optional[Dict] = None
    page_state: Optional[Dict] = None
    last_activity: Optional[float] = None
    monitoring_enabled: bool = True
    
class ChromiumRestartManager:
    """Chromium重启管理器"""
    
    def __init__(self, browser_manager, config: Dict = None):
        self.browser_manager = browser_manager
        self.config = config or {}
        
        # 重启配置
        self.restart_interval = self.config.get('restart_interval', 3600)  # 默认1小时重启一次
        self.min_restart_interval = self.config.get('min_restart_interval', 1800)  # 最小30分钟
        self.max_restart_interval = self.config.get('max_restart_interval', 7200)  # 最大2小时
        self.memory_threshold_mb = self.config.get('memory_threshold_mb', 1024)  # 内存阈值1GB
        
        # 状态管理
        self.last_restart_time = time.time()
        self.start_time = time.time()  # 记录启动时间用于计算运行时长
        self.restart_count = 0
        self.restart_task = None
        self.is_restarting = False
        self.restart_enabled = True
        
        # 状态保存文件
        self.state_file = os.path.join(os.path.dirname(__file__), 'restart_state.json')
        
        # 重启统计
        self.restart_stats = {
            'total_restarts': 0,
            'successful_restarts': 0,
            'failed_restarts': 0,
            'average_restart_time': 0,
            'last_restart_duration': 0,
            'memory_triggered_restarts': 0,
            'scheduled_restarts': 0
        }
        
        logging.info(f"ChromiumRestartManager初始化完成，重启间隔: {self.restart_interval}秒")
    
    async def start(self):
        """启动重启管理器（公共接口）"""
        await self.start_restart_scheduler()
    
    async def stop(self):
        """停止重启管理器（公共接口）"""
        await self.stop_restart_scheduler()
    
    async def start_restart_scheduler(self):
        """启动重启调度器"""
        if self.restart_task and not self.restart_task.done():
            logging.warning("重启调度器已在运行")
            return
            
        self.restart_task = asyncio.create_task(self._restart_scheduler_loop())
        logging.info("Chromium重启调度器已启动")
    
    async def stop_restart_scheduler(self):
        """停止重启调度器"""
        if self.restart_task:
            self.restart_task.cancel()
            try:
                await self.restart_task
            except asyncio.CancelledError:
                pass
            self.restart_task = None
        logging.info("Chromium重启调度器已停止")
    
    async def _restart_scheduler_loop(self):
        """重启调度器主循环"""
        try:
            while True:
                if not self.restart_enabled:
                    await asyncio.sleep(60)  # 禁用时每分钟检查一次
                    continue
                
                current_time = time.time()
                time_since_last_restart = current_time - self.last_restart_time
                
                # 检查是否需要重启
                should_restart = False
                restart_reason = ""
                
                # 1. 定时重启检查
                if time_since_last_restart >= self.restart_interval:
                    should_restart = True
                    restart_reason = "scheduled"
                
                # 2. 内存使用检查
                memory_usage = await self._get_memory_usage()
                if memory_usage and memory_usage > self.memory_threshold_mb:
                    if time_since_last_restart >= self.min_restart_interval:
                        should_restart = True
                        restart_reason = "memory_threshold"
                
                # 3. 执行重启
                if should_restart:
                    await self._perform_restart(restart_reason)
                
                # 等待下次检查（每5分钟检查一次）
                await asyncio.sleep(300)
                
        except asyncio.CancelledError:
            logging.info("重启调度器循环被取消")
        except Exception as e:
            logging.error(f"重启调度器循环异常: {e}")
    
    async def _get_memory_usage(self) -> Optional[float]:
        """获取当前内存使用量（MB）"""
        try:
            if not self.browser_manager.browser:
                return None
            
            # 获取浏览器进程内存使用
            # 这里可以通过系统调用或浏览器API获取内存使用情况
            # 暂时返回模拟值，实际实现需要根据具体环境调整
            return None
        except Exception as e:
            logging.error(f"获取内存使用量失败: {e}")
            return None
    
    async def _perform_restart(self, reason: str = "manual"):
        """执行Chromium重启"""
        if self.is_restarting:
            logging.warning("重启操作正在进行中，跳过本次重启")
            return False
        
        self.is_restarting = True
        restart_start_time = time.time()
        
        try:
            logging.info(f"开始执行Chromium重启，原因: {reason}")
            
            # 1. 保存当前状态
            saved_states = await self._save_current_state()
            
            # 2. 优雅关闭当前浏览器
            await self._graceful_shutdown()
            
            # 3. 等待一段时间确保进程完全关闭
            await asyncio.sleep(2)
            
            # 4. 重新初始化浏览器
            await self._reinitialize_browser()
            
            # 5. 恢复保存的状态
            await self._restore_state(saved_states)
            
            # 6. 更新统计信息
            restart_duration = time.time() - restart_start_time
            self._update_restart_stats(True, restart_duration, reason)
            
            self.last_restart_time = time.time()
            self.restart_count += 1
            
            logging.info(f"Chromium重启完成，耗时: {restart_duration:.2f}秒")
            return True
            
        except Exception as e:
            restart_duration = time.time() - restart_start_time
            self._update_restart_stats(False, restart_duration, reason)
            logging.error(f"Chromium重启失败: {e}")
            return False
        finally:
            self.is_restarting = False
    
    async def _save_current_state(self) -> List[RestartState]:
        """保存当前所有页面状态"""
        saved_states = []
        
        try:
            if not self.browser_manager.pages:
                return saved_states
            
            for url_id, page in self.browser_manager.pages.items():
                try:
                    # 获取页面基本信息
                    url = page.url
                    
                    # 获取Cookie数据
                    cookies_data = None
                    if self.browser_manager.context:
                        cookies = await self.browser_manager.context.cookies()
                        cookies_data = [cookie for cookie in cookies]
                    
                    # 获取页面状态（如果有自定义状态保存逻辑）
                    page_state = await self._extract_page_state(page)
                    
                    # 获取最后活动时间
                    last_activity = self.browser_manager.page_sessions.get(url_id, {}).get('last_activity')
                    
                    # 获取监控状态
                    monitoring_enabled = url_id in self.browser_manager.pages
                    
                    # 获取当前脚本信息
                    current_script_info = self.browser_manager.get_current_script_info()
                    script_name = current_script_info.get('filename', 'danmaku_listener.js')
                    
                    state = RestartState(
                        url_id=url_id,
                        url=url,
                        script_name=script_name,
                        cookies_data=cookies_data,
                        page_state=page_state,
                        last_activity=last_activity,
                        monitoring_enabled=monitoring_enabled
                    )
                    
                    saved_states.append(state)
                    logging.info(f"已保存页面状态: {url_id}")
                    
                except Exception as e:
                    logging.error(f"保存页面{url_id}状态失败: {e}")
            
            # 保存状态到文件
            await self._save_state_to_file(saved_states)
            
        except Exception as e:
            logging.error(f"保存当前状态失败: {e}")
        
        return saved_states
    
    async def _extract_page_state(self, page) -> Optional[Dict]:
        """提取页面状态信息"""
        try:
            # 获取页面的自定义状态（如滚动位置、表单数据等）
            state = await page.evaluate("""
                () => {
                    return {
                        scroll_position: {
                            x: window.scrollX,
                            y: window.scrollY
                        },
                        viewport: {
                            width: window.innerWidth,
                            height: window.innerHeight
                        },
                        timestamp: Date.now()
                    };
                }
            """)
            return state
        except Exception as e:
            logging.error(f"提取页面状态失败: {e}")
            return None
    
    async def _save_state_to_file(self, states: List[RestartState]):
        """保存状态到文件"""
        try:
            state_data = {
                'timestamp': datetime.now().isoformat(),
                'restart_count': self.restart_count,
                'states': [asdict(state) for state in states]
            }
            
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logging.error(f"保存状态文件失败: {e}")
    
    async def _graceful_shutdown(self):
        """优雅关闭当前浏览器"""
        try:
            # 停止所有监控
            await self.browser_manager.stop_all_monitoring()
            
            # 执行清理操作
            await self.browser_manager.cleanup()
            
            logging.info("浏览器已优雅关闭")
            
        except Exception as e:
            logging.error(f"优雅关闭浏览器失败: {e}")
    
    async def _reinitialize_browser(self):
        """重新初始化浏览器"""
        try:
            # 重新初始化浏览器，优先沿用当前浏览器模式
            # 若当前模式未知，则回退到配置中的设置
            # 优先使用 BrowserManager 的全局浏览器配置
            browser_config = (self.browser_manager.config.get('browser', {})
                              if getattr(self.browser_manager, 'config', None)
                              else {})

            # 统一布尔规范化方法，确保字符串/数字输入也能正确解析
            def _to_bool(value, default=False):
                try:
                    if isinstance(value, bool):
                        return value
                    if value is None:
                        return default
                    if isinstance(value, (int, float)):
                        return value != 0
                    if isinstance(value, str):
                        v = value.strip().lower()
                        if v in ("true", "1", "yes", "y", "on"): return True
                        if v in ("false", "0", "no", "n", "off"): return False
                        return default
                    return default
                except:
                    return default

            current_mode = getattr(self.browser_manager, 'current_headless_mode', None)
            # 若当前模式未知，回退到全局配置的 headless_mode（默认False=有头）或旧键 headless
            fallback = browser_config.get('headless_mode', browser_config.get('headless', False))
            headless = current_mode if current_mode is not None else _to_bool(fallback, False)
            browser_type = browser_config.get('type', 'chromium')

            # 打印提示，便于调试确认当前模式
            logging.info(f"重启时沿用浏览器模式: headless={headless} (当前记录: {current_mode})")

            await self.browser_manager.initialize(headless=headless, browser_type=browser_type)
            
            logging.info("浏览器重新初始化完成")
            
        except Exception as e:
            logging.error(f"重新初始化浏览器失败: {e}")
            raise
    
    async def _restore_state(self, saved_states: List[RestartState]):
        """恢复保存的状态（并行优化）"""
        try:
            if not saved_states:
                return

            async def _restore_single_state(state: RestartState):
                try:
                    # 恢复Cookie（若存在）
                    if state.cookies_data and self.browser_manager.context:
                        await self.browser_manager.context.add_cookies(state.cookies_data)

                    # 重新打开页面并开始监控（并行执行，不获取外部锁）
                    if state.monitoring_enabled:
                        success = await self.browser_manager.start_monitoring(
                            state.url_id,
                            acquire_lock=False
                        )

                        if success:
                            # 恢复页面状态
                            if state.page_state:
                                await self._restore_page_state(state.url_id, state.page_state)
                            logging.info(f"已恢复页面监控: {state.url_id}")
                        else:
                            logging.error(f"恢复页面监控失败: {state.url_id}")
                except Exception as e:
                    logging.error(f"恢复页面{state.url_id}状态失败: {e}")

            # 并行恢复所有页面
            await asyncio.gather(*[ _restore_single_state(state) for state in saved_states ])

        except Exception as e:
            logging.error(f"恢复状态失败: {e}")
    
    async def _restore_page_state(self, url_id: str, page_state: Dict):
        """恢复页面状态"""
        try:
            page = self.browser_manager.pages.get(url_id)
            if not page:
                return
            
            # 恢复滚动位置
            if 'scroll_position' in page_state:
                scroll_pos = page_state['scroll_position']
                await page.evaluate(f"""
                    window.scrollTo({scroll_pos['x']}, {scroll_pos['y']});
                """)
            
        except Exception as e:
            logging.error(f"恢复页面状态失败: {e}")
    
    def _update_restart_stats(self, success: bool, duration: float, reason: str):
        """更新重启统计信息"""
        self.restart_stats['total_restarts'] += 1
        self.restart_stats['last_restart_duration'] = duration
        
        if success:
            self.restart_stats['successful_restarts'] += 1
        else:
            self.restart_stats['failed_restarts'] += 1
        
        # 更新平均重启时间
        total_successful = self.restart_stats['successful_restarts']
        if total_successful > 0:
            current_avg = self.restart_stats['average_restart_time']
            self.restart_stats['average_restart_time'] = (
                (current_avg * (total_successful - 1) + duration) / total_successful
            )
        
        # 按原因分类统计
        if reason == "memory_threshold":
            self.restart_stats['memory_triggered_restarts'] += 1
        elif reason == "scheduled":
            self.restart_stats['scheduled_restarts'] += 1
    
    async def manual_restart(self) -> bool:
        """手动触发重启"""
        return await self._perform_restart("manual")
    
    async def trigger_restart(self, reason: str = "手动触发") -> bool:
        """触发重启（公共接口）"""
        return await self._perform_restart(reason)
    
    async def get_status(self) -> Dict[str, Any]:
        """获取重启管理器状态（公共接口）"""
        current_time = time.time()
        next_restart_timestamp = self.last_restart_time + self.restart_interval
        
        # 计算运行时长（从启动时间到现在）
        uptime = current_time - self.start_time if hasattr(self, 'start_time') else 0
        
        # 获取内存使用情况
        memory_usage = await self._get_memory_usage() or 0
        
        # 格式化下次重启时间
        next_restart_time = datetime.fromtimestamp(next_restart_timestamp).strftime('%Y-%m-%d %H:%M:%S') if next_restart_timestamp > current_time else '立即'
        
        return {
            # 前端期望的字段
            'is_active': self.restart_enabled,
            'is_paused': not self.restart_enabled,
            'next_restart_time': next_restart_time,
            'uptime': uptime,
            'memory_usage': memory_usage,
            
            # 保留原有字段以兼容其他代码
            'restart_enabled': self.restart_enabled,
            'is_restarting': self.is_restarting,
            'last_restart_time': self.last_restart_time,
            'next_scheduled_restart': next_restart_timestamp,
            'time_until_next_restart': max(0, next_restart_timestamp - current_time),
            'restart_interval': self.restart_interval,
            'memory_threshold_mb': self.memory_threshold_mb,
            'restart_stats': self.restart_stats,
            'config': self.config
        }
    
    def get_restart_stats(self) -> Dict:
        """获取重启统计信息"""
        return {
            **self.restart_stats,
            'restart_enabled': self.restart_enabled,
            'is_restarting': self.is_restarting,
            'last_restart_time': self.last_restart_time,
            'next_scheduled_restart': self.last_restart_time + self.restart_interval,
            'time_until_next_restart': max(0, (self.last_restart_time + self.restart_interval) - time.time())
        }
    
    def set_restart_enabled(self, enabled: bool):
        """启用/禁用自动重启"""
        self.restart_enabled = enabled
        logging.info(f"自动重启已{'启用' if enabled else '禁用'}")
    
    def update_restart_interval(self, interval: int):
        """更新重启间隔"""
        if interval < self.min_restart_interval:
            interval = self.min_restart_interval
        elif interval > self.max_restart_interval:
            interval = self.max_restart_interval
        
        self.restart_interval = interval
        logging.info(f"重启间隔已更新为: {interval}秒")