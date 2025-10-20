#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置管理使用示例

这个文件展示了如何使用增强的配置管理器
"""

import logging
import time
from pathlib import Path
from .enhanced_config import EnhancedConfig
from .config_migration import create_config_manager, migrate_config

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def example_basic_usage():
    """基本使用示例"""
    print("=== 基本使用示例 ===")
    
    # 创建配置管理器
    config = create_config_manager("example_config.json", auto_reload=False)
    
    # 读取配置
    webui_port = config.get("webui", "port", default=8081)
    print(f"WebUI端口: {webui_port}")
    
    # 设置配置
    success = config.set("webui", "port", 8082)
    print(f"设置端口成功: {success}")
    
    # 保存配置
    config.save()
    print("配置已保存")
    
    # 获取整个webui配置
    webui_config = config.get("webui")
    print(f"WebUI配置: {webui_config}")

def example_validation():
    """配置验证示例"""
    print("\n=== 配置验证示例 ===")
    
    config = create_config_manager("validation_config.json", auto_reload=False)
    
    # 尝试设置无效端口
    success = config.set("webui", "port", 99999)
    print(f"设置无效端口 99999: {success}")
    
    # 尝试设置无效IP
    success = config.set("webui", "ip", "invalid_ip")
    print(f"设置无效IP: {success}")
    
    # 设置有效值
    success = config.set("webui", "port", 8080)
    print(f"设置有效端口 8080: {success}")
    
    success = config.set("webui", "ip", "192.168.1.100")
    print(f"设置有效IP: {success}")

def example_auto_reload():
    """自动重载示例"""
    print("\n=== 自动重载示例 ===")
    
    config_file = "auto_reload_config.json"
    
    # 创建带自动重载的配置管理器
    config = create_config_manager(config_file, auto_reload=True)
    
    # 添加变更回调
    def on_config_change(new_config):
        print(f"配置已变更，新的WebUI端口: {new_config.get('webui', {}).get('port', 'N/A')}")
    
    config.add_change_callback(on_config_change)
    
    print(f"当前端口: {config.get('webui', 'port')}")
    
    # 模拟外部修改配置文件
    print("请在另一个程序中修改配置文件，或者等待5秒后自动修改...")
    
    # 等待5秒后自动修改
    time.sleep(5)
    
    # 直接修改配置文件来触发重载
    import json
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        data['webui']['port'] = 9999
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print("已修改配置文件，等待自动重载...")
        time.sleep(2)  # 等待自动重载
        
    except Exception as e:
        print(f"修改配置文件失败: {e}")
    
    # 停止自动重载
    config.stop_auto_reload()
    print("自动重载已停止")

def example_migration():
    """配置迁移示例"""
    print("\n=== 配置迁移示例 ===")
    
    # 创建一个旧格式的配置文件
    old_config = {
        "webui": {
            "port": 8081
        },
        "play_audio": {
            "enable": True
        },
        "custom_field": "custom_value"
    }
    
    old_config_file = "old_config.json"
    new_config_file = "migrated_config.json"
    
    # 保存旧配置
    import json
    with open(old_config_file, 'w', encoding='utf-8') as f:
        json.dump(old_config, f, ensure_ascii=False, indent=2)
    
    print(f"已创建旧配置文件: {old_config_file}")
    
    # 执行迁移
    success = migrate_config(old_config_file, new_config_file)
    print(f"迁移成功: {success}")
    
    if success:
        # 验证迁移结果
        migrated_config = create_config_manager(new_config_file, auto_reload=False)
        print(f"迁移后的WebUI端口: {migrated_config.get('webui', 'port')}")
        print(f"迁移后的自定义字段: {migrated_config.get('custom_field')}")
        print(f"默认的音频播放器: {migrated_config.get('play_audio', 'player')}")

def example_nested_config():
    """嵌套配置示例"""
    print("\n=== 嵌套配置示例 ===")
    
    config = create_config_manager("nested_config.json", auto_reload=False)
    
    # 设置深层嵌套配置
    config.set("llm", "chatgpt", "model", "gpt-4")
    config.set("llm", "chatgpt", "temperature", 0.7)
    config.set("llm", "claude", "model", "claude-3")
    
    # 读取嵌套配置
    chatgpt_model = config.get("llm", "chatgpt", "model")
    print(f"ChatGPT模型: {chatgpt_model}")
    
    # 获取整个LLM配置
    llm_config = config.get("llm")
    print(f"LLM配置: {llm_config}")
    
    # 使用默认值
    unknown_value = config.get("unknown", "path", default="default_value")
    print(f"未知配置项（使用默认值）: {unknown_value}")

def example_custom_validation():
    """自定义验证示例"""
    print("\n=== 自定义验证示例 ===")
    
    config = create_config_manager("custom_validation_config.json", auto_reload=False)
    
    # 添加自定义验证规则
    config.validator.add_required_field("api_key")
    config.validator.add_type_constraint("max_tokens", int)
    config.validator.add_value_constraint(
        "max_tokens",
        lambda x: 1 <= x <= 4000,
        "max_tokens必须在1-4000范围内"
    )
    
    # 测试验证
    config.set("api_key", "test_key")
    config.set("max_tokens", 2000)
    
    # 尝试设置无效值
    success = config.set("max_tokens", 5000)
    print(f"设置无效max_tokens: {success}")
    
    # 验证当前配置
    errors = config.validator.validate(config.config)
    if errors:
        print(f"配置验证错误: {errors}")
    else:
        print("配置验证通过")

def cleanup_example_files():
    """清理示例文件"""
    example_files = [
        "example_config.json",
        "validation_config.json", 
        "auto_reload_config.json",
        "old_config.json",
        "migrated_config.json",
        "nested_config.json",
        "custom_validation_config.json"
    ]
    
    for file in example_files:
        try:
            Path(file).unlink(missing_ok=True)
        except Exception as e:
            print(f"删除文件 {file} 失败: {e}")

if __name__ == "__main__":
    try:
        example_basic_usage()
        example_validation()
        example_nested_config()
        example_custom_validation()
        example_migration()
        # example_auto_reload()  # 注释掉，因为需要交互
        
    except KeyboardInterrupt:
        print("\n示例被中断")
    except Exception as e:
        print(f"示例执行出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n清理示例文件...")
        cleanup_example_files()
        print("示例完成")