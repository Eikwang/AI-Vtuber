"""
性能优化器
负责监控和优化Chromium重启过程中的性能表现
提供重启效率分析和性能影响评估
"""

import asyncio
import time
import logging
import psutil
import json
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import deque
import statistics

@dataclass
class PerformanceMetrics:
    """性能指标数据类"""
    timestamp: float
    cpu_usage: float
    memory_usage: float
    memory_available: float
    disk_io_read: float
    disk_io_write: float
    network_io_sent: float
    network_io_recv: float
    browser_processes: int
    total_processes: int
    restart_duration: Optional[float] = None
    restart_phase: Optional[str] = None

@dataclass
class RestartPerformanceReport:
    """重启性能报告数据类"""
    restart_id: str
    start_time: float
    end_time: float
    total_duration: float
    phases: Dict[str, float] = field(default_factory=dict)
    metrics_before: Optional[PerformanceMetrics] = None
    metrics_after: Optional[PerformanceMetrics] = None
    metrics_during: List[PerformanceMetrics] = field(default_factory=list)
    success: bool = True
    error_message: Optional[str] = None
    optimization_suggestions: List[str] = field(default_factory=list)

class PerformanceOptimizer:
    """性能优化器"""
    
    def __init__(self, config: Dict = None):
        self.config = config or {}
        
        # 性能监控配置
        self.monitoring_interval = self.config.get('monitoring_interval', 1.0)  # 1秒监控间隔
        self.metrics_history_size = self.config.get('metrics_history_size', 300)  # 保留5分钟历史
        self.performance_threshold = self.config.get('performance_threshold', {
            'cpu_usage': 80.0,  # CPU使用率阈值
            'memory_usage': 85.0,  # 内存使用率阈值
            'restart_duration': 30.0,  # 重启时长阈值（秒）
        })
        
        # 数据存储
        self.metrics_history = deque(maxlen=self.metrics_history_size)
        self.restart_reports = []
        self.current_restart_id = None
        self.current_restart_start = None
        self.current_restart_phases = {}
        
        # 监控任务
        self.monitoring_task = None
        self.is_monitoring = False
        
        # 性能基线
        self.baseline_metrics = None
        self.baseline_calculated = False
        
        # 报告文件路径
        self.reports_dir = os.path.join(os.path.dirname(__file__), 'performance_reports')
        self.ensure_reports_directory()
        
        logging.info("性能优化器初始化完成")
    
    def ensure_reports_directory(self):
        """确保报告目录存在"""
        if not os.path.exists(self.reports_dir):
            os.makedirs(self.reports_dir, exist_ok=True)
    
    async def start_monitoring(self):
        """开始性能监控"""
        if self.is_monitoring:
            logging.warning("性能监控已在运行")
            return
        
        self.is_monitoring = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        logging.info("性能监控已启动")
    
    async def stop_monitoring(self):
        """停止性能监控"""
        if not self.is_monitoring:
            return
        
        self.is_monitoring = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            self.monitoring_task = None
        
        logging.info("性能监控已停止")
    
    async def _monitoring_loop(self):
        """性能监控主循环"""
        try:
            while self.is_monitoring:
                metrics = await self._collect_metrics()
                if metrics:
                    self.metrics_history.append(metrics)
                    
                    # 如果正在重启，记录重启期间的指标
                    if self.current_restart_id:
                        # 这里可以添加重启期间的特殊处理逻辑
                        pass
                
                await asyncio.sleep(self.monitoring_interval)
                
        except asyncio.CancelledError:
            logging.info("性能监控循环被取消")
        except Exception as e:
            logging.error(f"性能监控循环异常: {e}")
    
    async def _collect_metrics(self) -> Optional[PerformanceMetrics]:
        """收集系统性能指标"""
        try:
            # CPU使用率
            cpu_usage = psutil.cpu_percent(interval=None)
            
            # 内存使用情况
            memory = psutil.virtual_memory()
            memory_usage = memory.percent
            memory_available = memory.available / (1024 * 1024 * 1024)  # GB
            
            # 磁盘IO
            disk_io = psutil.disk_io_counters()
            disk_io_read = disk_io.read_bytes / (1024 * 1024) if disk_io else 0  # MB
            disk_io_write = disk_io.write_bytes / (1024 * 1024) if disk_io else 0  # MB
            
            # 网络IO
            network_io = psutil.net_io_counters()
            network_io_sent = network_io.bytes_sent / (1024 * 1024) if network_io else 0  # MB
            network_io_recv = network_io.bytes_recv / (1024 * 1024) if network_io else 0  # MB
            
            # 进程统计
            browser_processes = len([p for p in psutil.process_iter(['name']) 
                                   if 'chrome' in p.info['name'].lower() or 'chromium' in p.info['name'].lower()])
            total_processes = len(list(psutil.process_iter()))
            
            return PerformanceMetrics(
                timestamp=time.time(),
                cpu_usage=cpu_usage,
                memory_usage=memory_usage,
                memory_available=memory_available,
                disk_io_read=disk_io_read,
                disk_io_write=disk_io_write,
                network_io_sent=network_io_sent,
                network_io_recv=network_io_recv,
                browser_processes=browser_processes,
                total_processes=total_processes
            )
            
        except Exception as e:
            logging.error(f"收集性能指标失败: {e}")
            return None
    
    async def start_restart_monitoring(self, restart_id: str) -> bool:
        """开始重启性能监控"""
        try:
            self.current_restart_id = restart_id
            self.current_restart_start = time.time()
            self.current_restart_phases = {}
            
            # 记录重启前的性能指标
            metrics_before = await self._collect_metrics()
            if metrics_before:
                # 可以在这里保存重启前的指标
                pass
            
            logging.info(f"开始重启性能监控: {restart_id}")
            return True
            
        except Exception as e:
            logging.error(f"开始重启性能监控失败: {e}")
            return False
    
    async def record_restart_phase(self, phase_name: str):
        """记录重启阶段"""
        if not self.current_restart_id:
            return
        
        current_time = time.time()
        if self.current_restart_start:
            phase_duration = current_time - self.current_restart_start
            self.current_restart_phases[phase_name] = phase_duration
            logging.debug(f"重启阶段 {phase_name}: {phase_duration:.2f}秒")
    
    async def end_restart_monitoring(self, success: bool = True, error_message: str = None) -> Optional[RestartPerformanceReport]:
        """结束重启性能监控并生成报告"""
        if not self.current_restart_id:
            return None
        
        try:
            end_time = time.time()
            total_duration = end_time - self.current_restart_start
            
            # 收集重启后的性能指标
            metrics_after = await self._collect_metrics()
            
            # 创建性能报告
            report = RestartPerformanceReport(
                restart_id=self.current_restart_id,
                start_time=self.current_restart_start,
                end_time=end_time,
                total_duration=total_duration,
                phases=self.current_restart_phases.copy(),
                metrics_after=metrics_after,
                success=success,
                error_message=error_message
            )
            
            # 生成优化建议
            report.optimization_suggestions = await self._generate_optimization_suggestions(report)
            
            # 保存报告
            self.restart_reports.append(report)
            await self._save_report(report)
            
            # 清理当前重启状态
            self.current_restart_id = None
            self.current_restart_start = None
            self.current_restart_phases = {}
            
            logging.info(f"重启性能监控结束，总耗时: {total_duration:.2f}秒")
            return report
            
        except Exception as e:
            logging.error(f"结束重启性能监控失败: {e}")
            return None
    
    async def _generate_optimization_suggestions(self, report: RestartPerformanceReport) -> List[str]:
        """生成优化建议"""
        suggestions = []
        
        try:
            # 检查重启时长
            if report.total_duration > self.performance_threshold['restart_duration']:
                suggestions.append(f"重启时长({report.total_duration:.1f}秒)超过阈值，建议优化重启流程")
            
            # 检查各阶段耗时
            for phase, duration in report.phases.items():
                if duration > 10.0:  # 单个阶段超过10秒
                    suggestions.append(f"阶段'{phase}'耗时过长({duration:.1f}秒)，需要优化")
            
            # 检查内存使用
            if report.metrics_after and report.metrics_after.memory_usage > self.performance_threshold['memory_usage']:
                suggestions.append(f"重启后内存使用率仍然较高({report.metrics_after.memory_usage:.1f}%)")
            
            # 检查CPU使用
            if report.metrics_after and report.metrics_after.cpu_usage > self.performance_threshold['cpu_usage']:
                suggestions.append(f"重启后CPU使用率较高({report.metrics_after.cpu_usage:.1f}%)")
            
            # 基于历史数据的建议
            if len(self.restart_reports) > 1:
                recent_reports = self.restart_reports[-5:]  # 最近5次重启
                avg_duration = statistics.mean([r.total_duration for r in recent_reports])
                
                if report.total_duration > avg_duration * 1.5:
                    suggestions.append("本次重启时长明显超过平均水平，建议检查系统负载")
            
            # 如果没有具体建议，给出通用建议
            if not suggestions and report.success:
                if report.total_duration < 15.0:
                    suggestions.append("重启性能良好，无需特殊优化")
                else:
                    suggestions.append("重启完成，可考虑进一步优化重启流程")
            
        except Exception as e:
            logging.error(f"生成优化建议失败: {e}")
            suggestions.append("无法生成优化建议，请检查性能监控系统")
        
        return suggestions
    
    async def _save_report(self, report: RestartPerformanceReport):
        """保存性能报告到文件"""
        try:
            report_file = os.path.join(
                self.reports_dir, 
                f"restart_report_{report.restart_id}_{int(report.start_time)}.json"
            )
            
            # 转换为可序列化的格式
            report_data = {
                'restart_id': report.restart_id,
                'start_time': report.start_time,
                'end_time': report.end_time,
                'total_duration': report.total_duration,
                'phases': report.phases,
                'success': report.success,
                'error_message': report.error_message,
                'optimization_suggestions': report.optimization_suggestions,
                'metrics_after': {
                    'timestamp': report.metrics_after.timestamp,
                    'cpu_usage': report.metrics_after.cpu_usage,
                    'memory_usage': report.metrics_after.memory_usage,
                    'memory_available': report.metrics_after.memory_available,
                    'browser_processes': report.metrics_after.browser_processes,
                    'total_processes': report.metrics_after.total_processes
                } if report.metrics_after else None
            }
            
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logging.error(f"保存性能报告失败: {e}")
    
    def get_performance_summary(self) -> Dict:
        """获取性能摘要"""
        try:
            if not self.restart_reports:
                return {
                    'total_restarts': 0,
                    'average_duration': 0,
                    'success_rate': 0,
                    'recent_performance': 'No data available'
                }
            
            successful_reports = [r for r in self.restart_reports if r.success]
            total_restarts = len(self.restart_reports)
            successful_restarts = len(successful_reports)
            
            # 计算平均重启时长
            avg_duration = statistics.mean([r.total_duration for r in successful_reports]) if successful_reports else 0
            
            # 计算成功率
            success_rate = (successful_restarts / total_restarts * 100) if total_restarts > 0 else 0
            
            # 最近性能趋势
            recent_reports = self.restart_reports[-5:] if len(self.restart_reports) >= 5 else self.restart_reports
            recent_avg = statistics.mean([r.total_duration for r in recent_reports if r.success]) if recent_reports else 0
            
            performance_trend = "stable"
            if len(self.restart_reports) > 5:
                older_avg = statistics.mean([r.total_duration for r in self.restart_reports[-10:-5] if r.success])
                if recent_avg > older_avg * 1.2:
                    performance_trend = "degrading"
                elif recent_avg < older_avg * 0.8:
                    performance_trend = "improving"
            
            return {
                'total_restarts': total_restarts,
                'successful_restarts': successful_restarts,
                'failed_restarts': total_restarts - successful_restarts,
                'success_rate': round(success_rate, 2),
                'average_duration': round(avg_duration, 2),
                'recent_average_duration': round(recent_avg, 2),
                'performance_trend': performance_trend,
                'fastest_restart': min([r.total_duration for r in successful_reports]) if successful_reports else 0,
                'slowest_restart': max([r.total_duration for r in successful_reports]) if successful_reports else 0,
                'current_monitoring': self.is_monitoring,
                'metrics_history_size': len(self.metrics_history)
            }
            
        except Exception as e:
            logging.error(f"获取性能摘要失败: {e}")
            return {'error': str(e)}
    
    def get_current_metrics(self) -> Optional[PerformanceMetrics]:
        """获取当前性能指标"""
        if self.metrics_history:
            return self.metrics_history[-1]
        return None
    
    def get_metrics_history(self, minutes: int = 5) -> List[PerformanceMetrics]:
        """获取指定时间范围内的性能指标历史"""
        if not self.metrics_history:
            return []
        
        cutoff_time = time.time() - (minutes * 60)
        return [m for m in self.metrics_history if m.timestamp >= cutoff_time]
    
    async def calculate_baseline_metrics(self, duration_minutes: int = 5):
        """计算性能基线指标"""
        try:
            logging.info(f"开始计算性能基线，持续时间: {duration_minutes}分钟")
            
            baseline_metrics = []
            end_time = time.time() + (duration_minutes * 60)
            
            while time.time() < end_time:
                metrics = await self._collect_metrics()
                if metrics:
                    baseline_metrics.append(metrics)
                await asyncio.sleep(self.monitoring_interval)
            
            if baseline_metrics:
                self.baseline_metrics = {
                    'cpu_usage': statistics.mean([m.cpu_usage for m in baseline_metrics]),
                    'memory_usage': statistics.mean([m.memory_usage for m in baseline_metrics]),
                    'memory_available': statistics.mean([m.memory_available for m in baseline_metrics]),
                    'browser_processes': statistics.mean([m.browser_processes for m in baseline_metrics]),
                    'calculated_at': time.time()
                }
                self.baseline_calculated = True
                logging.info("性能基线计算完成")
            
        except Exception as e:
            logging.error(f"计算性能基线失败: {e}")
    
    def get_optimization_recommendations(self) -> List[str]:
        """获取系统优化建议"""
        recommendations = []
        
        try:
            if not self.restart_reports:
                return ["暂无重启数据，无法提供优化建议"]
            
            # 分析重启性能趋势
            recent_reports = self.restart_reports[-10:] if len(self.restart_reports) >= 10 else self.restart_reports
            avg_duration = statistics.mean([r.total_duration for r in recent_reports if r.success])
            
            if avg_duration > 30:
                recommendations.append("重启时间过长，建议优化浏览器初始化流程")
            
            # 分析失败率
            failed_count = len([r for r in recent_reports if not r.success])
            if failed_count > len(recent_reports) * 0.1:  # 失败率超过10%
                recommendations.append("重启失败率较高，建议检查系统稳定性")
            
            # 分析当前系统状态
            current_metrics = self.get_current_metrics()
            if current_metrics:
                if current_metrics.memory_usage > 85:
                    recommendations.append("当前内存使用率过高，建议增加重启频率")
                
                if current_metrics.cpu_usage > 80:
                    recommendations.append("当前CPU使用率过高，可能影响重启性能")
            
            # 基于历史数据的建议
            if len(self.restart_reports) > 20:
                phase_analysis = {}
                for report in recent_reports:
                    for phase, duration in report.phases.items():
                        if phase not in phase_analysis:
                            phase_analysis[phase] = []
                        phase_analysis[phase].append(duration)
                
                for phase, durations in phase_analysis.items():
                    avg_phase_duration = statistics.mean(durations)
                    if avg_phase_duration > 10:
                        recommendations.append(f"阶段'{phase}'平均耗时过长({avg_phase_duration:.1f}秒)，需要优化")
            
            if not recommendations:
                recommendations.append("系统性能良好，继续保持当前配置")
            
        except Exception as e:
            logging.error(f"获取优化建议失败: {e}")
            recommendations.append("无法分析性能数据，请检查监控系统")
        
        return recommendations