# DanmakuListener

一个功能强大的直播弹幕监听系统，支持多种直播平台的弹幕、礼物、点赞等消息的实时接收、处理和转发。

## 功能特性

- 🔗 **WebSocket服务器**：接收来自浏览器脚本的弹幕数据并进行处理
- 🌐 **实时Web界面**：显示弹幕、礼物和点赞消息，支持响应式设计
- 🚫 **关键词过滤**：支持添加和删除屏蔽词，自动持久化存储
- 💾 **Cookie管理**：支持Cookie的自动保存和加载，优化直播平台登录状态维持
- 🎨 **消息类型区分**：不同类型消息（弹幕、礼物、点赞等）有视觉区分
- ⏰ **实时监控**：监控各直播间的连接状态和消息统计
- 🔌 **API转发**：支持将弹幕数据转发到其他系统（如AI-VTUBER）
- 🛠️ **浏览器自动化**：基于Playwright的浏览器自动化管理
- 📋 **多平台支持**：兼容多种主流直播平台

## 支持的直播平台

- 斗鱼 (douyu.com)
- 快手 (kuaishou.com)
- 拼多多 (yangkeduo.com)
- 1688 (1688.com)
- 淘宝 (taobao.com)
- 小红书 (xiaohongshu.com)
- 微信视频号 (weixin.qq.com)
- 巨量百应 (jinritemai.com)
- TikTok (tiktok.com)
- 抖音 (douyin.com)

## 安装和设置

### 1. 环境要求

- Python 3.7+
- 依赖库: aiohttp, playwright, websockets, aiohttp_cors, psutil

### 2. 安装依赖

```bash
cd DanmakuListener
pip install -r requirements.txt
# 安装Playwright浏览器
sudo playwright install
# 在Windows上使用:
# playwright install
```

### 3. 启动服务器

可以通过以下方式之一启动服务器:

**方式1: 直接运行Python脚本**
```bash
cd DanmakuListener
python app.py
```

**方式2: 使用批处理文件(Windows)**
```bash
双击运行 "1.双击我启动程序.bat" 或 "启动优化版本.bat"
```

服务器将在 `http://localhost:8765` 启动（可在config.json中配置）。

### 4. 安装浏览器监听脚本

1. 在浏览器中安装Tampermonkey扩展
2. 导入脚本文件：`直播监听脚本/通用平台_V4_内存优化版.js`
3. 确保脚本已启用

## 使用方法

### 基本使用

1. 启动DanmakuListener服务器
2. 服务器启动后会自动打开Web界面 `http://localhost:8765`
3. 在另一个标签页中打开支持的直播平台
4. Tampermonkey脚本会自动连接到WebSocket服务器
5. 弹幕消息将实时显示在Web界面中

### 配置文件

系统主要配置保存在 `config.json` 文件中，可以根据需要进行调整：

- **server**: 服务器相关配置（端口、主机等）
- **browser**: 浏览器相关配置（无头模式、内存优化等）
- **websocket**: WebSocket相关配置（最大客户端数、队列大小等）
- **api_forwarding**: API转发配置（是否启用、目标地址等）

### 关键词过滤

- 在Web界面底部的输入框中输入要屏蔽的关键词
- 点击"添加屏蔽词"按钮
- 包含屏蔽词的弹幕将不会显示
- 点击已添加的屏蔽词可以删除它
- 屏蔽词列表会自动保存到 `blocked_keywords.json` 文件中

## 消息类型

- **💬 评论消息**：普通弹幕评论
- **🎁 礼物消息**：用户送礼信息
- **👍 点赞消息**：用户点赞信息

每种消息类型都有不同的颜色和图标进行区分。

## 系统组件说明

### 核心文件

- **app.py**: 主应用程序入口，管理WebSocket服务器和API路由
- **browser_manager.py**: 管理浏览器实例和页面，处理Cookie保存和加载
- **monitor_manager.py**: 监控各直播间的连接状态
- **url_manager.py**: 管理直播URL配置
- **websocket_client.py**: 连接到AI-VTUBER的WebSocket客户端
- **optimized_websocket_management.py**: 优化的WebSocket连接管理

### 工具文件

- **fix_browser_manager_cookies.py**: 修复浏览器Cookie加载逻辑的工具
- **cleanup_script.py**: 代码清理工具，用于移除无用文件
- **code_cleanup_plan.md**: 代码清理计划文档

## 故障排除

### WebSocket连接失败

1. 确保服务器正在运行
2. 检查防火墙设置，确保8765端口可访问（或config.json中配置的端口）
3. 确认浏览器脚本中的WebSocket URL正确

### 弹幕不显示

1. 检查浏览器控制台是否有错误信息
2. 确认当前直播平台在支持列表中
3. 检查Tampermonkey脚本是否正常运行
4. 检查config.json中相关功能是否启用

### Cookie问题

如果遇到Cookie保存或加载问题，可以使用提供的修复工具：
```bash
python fix_browser_manager_cookies.py
```

### 屏蔽词不生效

1. 确认屏蔽词已成功添加（在界面中显示）
2. 检查 `blocked_keywords.json` 文件是否存在且包含屏蔽词
3. 重启服务器以重新加载屏蔽词列表

## 代码维护建议

1. **定期清理**：使用cleanup_script.py定期清理临时文件和测试脚本
2. **备份重要文件**：特别是config.json和cookie目录中的文件
3. **版本控制**：建议使用Git等工具进行代码版本管理
4. **文档更新**：功能变更后及时更新相关文档

## 注意事项

1. 系统运行过程中可能会生成临时文件和日志，占用一定磁盘空间
2. 浏览器自动化功能可能会消耗较多系统资源，可在config.json中调整相关配置
3. 定期重启服务有助于释放系统资源和保持系统稳定性

## 许可证

GPL-3.0