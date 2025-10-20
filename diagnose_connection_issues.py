import os
import json
import subprocess
import asyncio
import socket
import time
from datetime import datetime

async def test_websocket_connection(host, port, path):
    """测试WebSocket连接是否可用"""
    try:
        # 尝试TCP连接测试
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result != 0:
            return False, f"无法连接到 {host}:{port}，端口未开放"
        
        # 如果安装了websockets库，进行更完整的测试
        try:
            import websockets
            uri = f"ws://{host}:{port}{path}"
            print(f"尝试WebSocket连接到: {uri}")
            
            async with websockets.connect(uri, timeout=5) as websocket:
                print("WebSocket连接成功!")
                return True, f"WebSocket连接到 {uri} 成功"
        except ImportError:
            return True, f"TCP端口 {host}:{port} 开放，但未安装websockets库进行完整测试"
        except Exception as e:
            return False, f"WebSocket连接失败: {str(e)}"
    except Exception as e:
        return False, f"连接测试失败: {str(e)}"


def check_cookie_directory(cookie_dir):
    """检查Cookie目录和文件"""
    results = []
    
    # 检查目录是否存在
    if not os.path.exists(cookie_dir):
        results.append(f"❌ Cookie目录不存在: {cookie_dir}")
        return results
    
    results.append(f"✅ Cookie目录存在: {cookie_dir}")
    
    # 检查目录权限
    if not os.access(cookie_dir, os.R_OK | os.W_OK):
        results.append(f"❌ 无权限读写Cookie目录")
    else:
        results.append(f"✅ 有Cookie目录读写权限")
    
    # 列出Cookie文件
    try:
        cookie_files = [f for f in os.listdir(cookie_dir) if f.endswith('.json')]
        if not cookie_files:
            results.append("❌ Cookie目录为空，没有JSON文件")
        else:
            results.append(f"✅ 找到 {len(cookie_files)} 个Cookie文件:")
            
            # 检查每个文件是否有效
            for file in cookie_files:
                file_path = os.path.join(cookie_dir, file)
                results.append(f"  - {file}")
                
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        cookies_count = len(data.get('cookies', []))
                        origins_count = len(data.get('origins', []))
                        results.append(f"    ✅ 有效数据 - cookies: {cookies_count}, origins: {origins_count}")
                except Exception as e:
                    results.append(f"    ❌ 文件无效: {str(e)}")
    except Exception as e:
        results.append(f"❌ 读取Cookie目录失败: {str(e)}")
    
    return results

def check_config_file(config_path):
    """检查配置文件中的问题"""
    results = []
    
    if not os.path.exists(config_path):
        results.append(f"❌ 配置文件不存在: {config_path}")
        return results
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 检查WebSocket配置冲突
        ws_client_port = config.get('websocket_client', {}).get('port')
        server_port = config.get('server', {}).get('port')
        
        if ws_client_port != server_port:
            results.append(f"⚠️ WebSocket配置冲突: 客户端端口={ws_client_port}, 服务器端口={server_port}")
        else:
            results.append(f"✅ WebSocket配置一致: 端口={ws_client_port}")
        
        # 检查重复配置项
        has_duplicate = False
        for key in config:
            if key.startswith('server.') or key.startswith('browser.'):
                has_duplicate = True
                results.append(f"⚠️ 发现重复配置项: {key}")
        
        if not has_duplicate:
            results.append("✅ 没有发现重复配置项")
        
        # 检查浏览器无头模式配置
        headless_mode = config.get('browser', {}).get('headless_mode')
        duplicate_headless = None
        if 'browser.headless_mode' in config:
            duplicate_headless = config['browser.headless_mode']
            # 转换类型以便比较
            if isinstance(duplicate_headless, str):
                duplicate_headless = duplicate_headless.lower() == 'true'
            
            if headless_mode != duplicate_headless:
                results.append(f"⚠️ 浏览器无头模式配置冲突: {headless_mode} vs {duplicate_headless}")
        
        # 检查Cookie相关配置
        cookie_persistence = config.get('browser', {}).get('cookie_persistence', True)
        auto_save_cookies = config.get('browser', {}).get('auto_save_cookies', True)
        
        results.append(f"✅ Cookie持久化: {'启用' if cookie_persistence else '禁用'}")
        results.append(f"✅ 自动保存Cookie: {'启用' if auto_save_cookies else '禁用'}")
            
    except Exception as e:
        results.append(f"❌ 读取配置文件失败: {str(e)}")
    
    return results

def check_processes():
    """检查相关进程是否运行"""
    results = []
    
    # 检查WssBarrageServer.exe进程
    try:
        # 使用tasklist命令检查进程
        output = subprocess.check_output(['tasklist', '/fi', 'IMAGENAME eq WssBarrageServer.exe'], universal_newlines=True)
        if 'WssBarrageServer.exe' in output:
            results.append("✅ WssBarrageServer.exe 进程正在运行")
        else:
            results.append("❌ WssBarrageServer.exe 进程未运行")
    except Exception as e:
        results.append(f"⚠️ 检查进程失败: {str(e)}")
    
    return results

async def main():
    print("===== DanmakuListener 连接问题诊断工具 =====")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"当前工作目录: {os.getcwd()}")
    print()
    
    # 1. 检查配置文件
    config_path = os.path.join('DanmakuListener', 'config.json')
    print("=== 配置文件检查 ===")
    config_results = check_config_file(config_path)
    for line in config_results:
        print(line)
    print()
    
    # 2. 检查Cookie目录
    cookie_dir = os.path.join(os.getcwd(), 'cookie')
    print("=== Cookie目录检查 ===")
    cookie_results = check_cookie_directory(cookie_dir)
    for line in cookie_results:
        print(line)
    print()
    
    # 3. 检查WebSocket连接
    print("=== WebSocket连接检查 ===")
    
    # 从配置文件读取WebSocket配置
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        ws_client = config.get('websocket_client', {})
        host = ws_client.get('host', '127.0.0.1')
        port = ws_client.get('port', 8765)
        path = ws_client.get('path', '/danmaku')
    except:
        host, port, path = '127.0.0.1', 8765, '/danmaku'
    
    print(f"测试WebSocket连接: ws://{host}:{port}{path}")
    ws_success, ws_message = await test_websocket_connection(host, port, path)
    print(f"{ws_message}")
    
    # 额外测试服务器端口
    print(f"\n测试服务器WebSocket端口: ws://{host}:{port}/ws")
    server_ws_success, server_ws_message = await test_websocket_connection(host, port, '/ws')
    print(f"{server_ws_message}")
    print()
    
    # 4. 检查进程
    print("=== 进程检查 ===")
    process_results = check_processes()
    for line in process_results:
        print(line)
    print()
    
    # 5. 提供修复建议
    print("=== 修复建议 ===")
    
    # 检查配置文件中的重复项
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 检查是否有重复配置项
        has_duplicate_config = any(key.startswith('server.') or key.startswith('browser.') for key in config)
        
        if has_duplicate_config:
            print("1. 删除配置文件中的重复配置项（以'server.'或'browser.'开头的键）")
        
        # 检查WebSocket端口是否一致
        ws_client_port = config.get('websocket_client', {}).get('port')
        server_port = config.get('server', {}).get('port')
        
        if ws_client_port != server_port:
            print(f"2. 确保WebSocket客户端端口({ws_client_port})与服务器端口({server_port})一致")
        
        # 检查Cookie目录
        if not os.path.exists(cookie_dir):
            print(f"3. 创建Cookie目录: {cookie_dir}")
        
        # 检查WssBarrageServer进程
        try:
            output = subprocess.check_output(['tasklist', '/fi', 'IMAGENAME eq WssBarrageServer.exe'], universal_newlines=True)
            if 'WssBarrageServer.exe' not in output:
                print("4. 手动启动WssBarrageServer.exe进程")
                print("   位置: D:\\AI\\AI-Vtuber\\DanmakuListener\\static\\Release\\WssBarrageServer.exe")
                print("   建议以管理员身份运行")
        except:
            pass
            
    except:
        print("无法读取配置文件进行详细分析")
    
    print("\n诊断完成！")

if __name__ == "__main__":
    asyncio.run(main())