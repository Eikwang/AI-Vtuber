#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接监控脚本
用于监控和分析DanmakuListener服务器的连接情况
"""

import subprocess
import time
import re
from collections import defaultdict, Counter

def get_port_connections(port=5001):
    """获取指定端口的连接信息"""
    try:
        # 使用netstat获取连接信息
        result = subprocess.run(['netstat', '-an'], 
                              capture_output=True, text=True, shell=True)
        
        connections = []
        for line in result.stdout.split('\n'):
            if f':{port}' in line:
                parts = line.split()
                if len(parts) >= 4:
                    protocol = parts[0]
                    local_addr = parts[1]
                    foreign_addr = parts[2]
                    state = parts[3] if len(parts) > 3 else 'UNKNOWN'
                    
                    connections.append({
                        'protocol': protocol,
                        'local': local_addr,
                        'foreign': foreign_addr,
                        'state': state
                    })
        
        return connections
    except Exception as e:
        print(f"获取连接信息失败: {e}")
        return []

def analyze_connections(connections):
    """分析连接模式"""
    state_count = Counter()
    foreign_ips = Counter()
    
    for conn in connections:
        state_count[conn['state']] += 1
        
        # 提取外部IP
        foreign = conn['foreign']
        if ':' in foreign:
            ip = foreign.split(':')[0]
            foreign_ips[ip] += 1
    
    return state_count, foreign_ips

def get_process_using_port(port=5001):
    """获取使用指定端口的进程信息"""
    try:
        # 使用netstat -ano获取进程ID
        result = subprocess.run(['netstat', '-ano'], 
                              capture_output=True, text=True, shell=True)
        
        for line in result.stdout.split('\n'):
            if f':{port}' in line and 'LISTENING' in line:
                parts = line.split()
                if len(parts) >= 5:
                    pid = parts[-1]
                    
                    # 获取进程名称
                    try:
                        tasklist_result = subprocess.run(
                            ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV'],
                            capture_output=True, text=True, shell=True
                        )
                        
                        lines = tasklist_result.stdout.strip().split('\n')
                        if len(lines) > 1:
                            # 解析CSV格式的输出
                            process_info = lines[1].split(',')
                            process_name = process_info[0].strip('"')
                            return f"{process_name} (PID: {pid})"
                    except:
                        return f"PID: {pid}"
        
        return "未找到监听进程"
    except Exception as e:
        return f"获取进程信息失败: {e}"

def monitor_connections(duration=60, interval=5):
    """监控连接变化"""
    print(f"开始监控端口5001的连接情况 (持续{duration}秒，每{interval}秒检查一次)")
    print("=" * 60)
    
    # 获取监听进程信息
    process_info = get_process_using_port()
    print(f"监听进程: {process_info}")
    print()
    
    start_time = time.time()
    previous_connections = set()
    
    while time.time() - start_time < duration:
        connections = get_port_connections()
        state_count, foreign_ips = analyze_connections(connections)
        
        # 创建当前连接的标识符集合
        current_connections = set()
        for conn in connections:
            conn_id = f"{conn['foreign']} -> {conn['local']} ({conn['state']})"
            current_connections.add(conn_id)
        
        # 检测新连接
        new_connections = current_connections - previous_connections
        closed_connections = previous_connections - current_connections
        
        timestamp = time.strftime('%H:%M:%S')
        print(f"[{timestamp}] 连接状态统计:")
        
        for state, count in state_count.most_common():
            print(f"  {state}: {count}")
        
        if new_connections:
            print(f"  新建连接 ({len(new_connections)}):")
            for conn in list(new_connections)[:5]:  # 只显示前5个
                print(f"    + {conn}")
        
        if closed_connections:
            print(f"  关闭连接 ({len(closed_connections)}):")
            for conn in list(closed_connections)[:5]:  # 只显示前5个
                print(f"    - {conn}")
        
        print(f"  总连接数: {len(connections)}")
        print()
        
        previous_connections = current_connections
        time.sleep(interval)
    
    print("监控完成")

def main():
    """主函数"""
    print("DanmakuListener 连接监控工具")
    print("=" * 40)
    
    # 显示当前连接状态
    print("当前连接状态:")
    connections = get_port_connections()
    
    if not connections:
        print("  没有发现端口5001的连接")
        return
    
    state_count, foreign_ips = analyze_connections(connections)
    
    print(f"  总连接数: {len(connections)}")
    print("  状态分布:")
    for state, count in state_count.most_common():
        print(f"    {state}: {count}")
    
    print("  外部IP分布:")
    for ip, count in foreign_ips.most_common():
        print(f"    {ip}: {count}")
    
    print()
    
    # 开始监控
    try:
        monitor_connections(duration=120, interval=3)
    except KeyboardInterrupt:
        print("\n监控已停止")

if __name__ == "__main__":
    main()