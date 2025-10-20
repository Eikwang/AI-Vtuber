// ==UserScript==
// @name         洛曦-直播弹幕监听助手 转发至本地WS服务端，巨量百应商品自动弹窗
// @namespace    http://tampermonkey.net/
// @version      3.0
// @description  观察指定 DOM 节点的变化以将数据发送到连接的WebSocket服务端
// @description  https://github.com/Ikaros-521/AI-Vtuber/blob/main/Scripts/%E7%9B%B4%E6%92%ADws%E8%84%9A%E6%9C%AC/%E6%B4%9B%E6%9B%A6%20%E7%9B%B4%E6%92%AD%E5%BC%B9%E5%B9%95%E7%9B%91%E5%90%AC%20%E8%BD%AC%E5%8F%91%E8%87%B3%E6%9C%AC%E5%9C%B0WS%E6%9C%8D%E5%8A%A1%E7%AB%AF.js
// @author       Ikaros
// @match        https://www.douyu.com/*
// @match        https://live.kuaishou.com/u/*
// @match        https://mobile.yangkeduo.com/*
// @match        https://live.1688.com/zb/play.html*
// @match        https://tbzb.taobao.com/live*
// @match        https://redlive.xiaohongshu.com/*
// @match        https://channels.weixin.qq.com/platform/live/*
// @match        https://buyin.jinritemai.com/dashboard/live/control*
// @match        https://ark.xiaohongshu.com/live_center_control*
// @match        https://www.tiktok.com/@*/live*
// @match        https://eos.douyin.com/livesite/live/current*
// @grant        none
// @namespace    https://greasyfork.org/scripts/490966
// @license      GPL-3.0
// @downloadURL https://update.greasyfork.org/scripts/490966/%E6%B4%9B%E6%9B%A6-%E7%9B%B4%E6%92%AD%E5%BC%B9%E5%B9%95%E7%9B%91%E5%90%AC%E5%8A%A9%E6%89%8B%20%E8%BD%AC%E5%8F%91%E8%87%B3%E6%9C%AC%E5%9C%B0WS%E6%9C%8D%E5%8A%A1%E7%AB%AF%EF%BC%8C%E5%B7%A8%E9%87%8F%E7%99%BE%E5%BA%94%E5%95%86%E5%93%81%E8%87%AA%E5%8A%A8%E5%BC%B9%E7%AA%97.user.js
// @updateURL https://update.greasyfork.org/scripts/490966/%E6%B4%9B%E6%9B%A6-%E7%9B%B4%E6%92%AD%E5%BC%B9%E5%B9%95%E7%9B%91%E5%90%AC%E5%8A%A9%E6%89%8B%20%E8%BD%AC%E5%8F%91%E8%87%B3%E6%9C%AC%E5%9C%B0WS%E6%9C%8D%E5%8A%A1%E7%AB%AF%EF%BC%8C%E5%B7%A8%E9%87%8F%E7%99%BE%E5%BA%94%E5%95%86%E5%93%81%E8%87%AA%E5%8A%A8%E5%BC%B9%E7%AA%97.meta.js
// ==/UserScript==

(function () {
  "use strict";


  let wsUrl = "ws://127.0.0.1:8765/ws";

  // 在文件开头添加一个函数，用于创建和显示消息框
  function showMessage(message, type = 'info') {
      const messageBox = document.createElement('div');
      messageBox.className = `message-box ${type}`;
      messageBox.innerText = message;

      // 设置样式，消息上方居中
      messageBox.style.position = 'fixed';
      messageBox.style.right = '40%';
      messageBox.style.transform = 'translateX(-50%)';
      messageBox.style.top = `${10 + (document.querySelectorAll('.message-box').length * 60)}px`; // 每个消息框之间的间距
      messageBox.style.zIndex = '9999';
      messageBox.style.padding = '10px';
      // 设置info、success、error、warning等多个颜色，要好看，参考element-ui
      messageBox.style.backgroundColor = type === 'info' ? '#409EFF' : type === 'success' ? '#67C23A' : type === 'warning' ? '#E6A23C' : '#F56C6C';
      messageBox.style.color = 'white';
      messageBox.style.borderRadius = '5px';
      messageBox.style.marginBottom = '10px';
      messageBox.style.transition = 'opacity 0.5s ease';
      // 字体要大
      messageBox.style.fontSize = '16px';

      document.body.appendChild(messageBox);

      // 自动消失
      setTimeout(() => {
          messageBox.style.opacity = '0';
          setTimeout(() => {
              // 安全检查：确保元素仍在DOM中
              if (messageBox.parentNode === document.body) {
                  document.body.removeChild(messageBox);
              }
          }, 500);
      }, 2000); // 2秒后消失

      // 限制消息框数量
      const messageBoxes = document.querySelectorAll('.message-box');
      if (messageBoxes.length > 5) { // 限制最多显示5个消息框
          const oldestBox = messageBoxes[0];
          // 安全检查：确保元素仍在DOM中
          if (oldestBox && oldestBox.parentNode === document.body) {
              document.body.removeChild(oldestBox);
          }
      }
  }

  showMessage("洛曦-直播弹幕监听助手 启动中，请稍等...", 'info');

  // 先识别平台
  const hostname = window.location.hostname;
  let detectedPlatform = null;
  
  if (hostname === "www.douyu.com") {
          detectedPlatform = "douyu";
          console.log("当前直播平台：斗鱼");
          showMessage("当前直播平台：斗鱼");
      } else if (hostname === "live.kuaishou.com") {
          detectedPlatform = "kuaishou";
          console.log("当前直播平台：快手");
          showMessage("当前直播平台：快手");
      } else if (hostname === "mobile.yangkeduo.com") {
          detectedPlatform = "pinduoduo";
          console.log("当前直播平台：拼多多");
          showMessage("当前直播平台：拼多多");
      } else if (hostname === "live.1688.com") {
          detectedPlatform = "1688";
          console.log("当前直播平台：1688");
          showMessage("当前直播平台：1688");
      } else if (hostname === "tbzb.taobao.com") {
          detectedPlatform = "taobao";
          console.log("当前直播平台：淘宝");
          showMessage("当前直播平台：淘宝");
      } else if (hostname === "redlive.xiaohongshu.com" || hostname === "ark.xiaohongshu.com") {
          detectedPlatform = "xiaohongshu";
          console.log("当前直播平台：小红书");
          showMessage("当前直播平台：小红书");
      } else if (hostname === "channels.weixin.qq.com") {
          detectedPlatform = "weixin";
          console.log("当前直播平台：微信视频号");
          showMessage("当前直播平台：微信视频号");
      } else if (hostname === "buyin.jinritemai.com") {
          detectedPlatform = "jinritemai";
          console.log("当前直播平台：巨量百应");
          showMessage("当前直播平台：巨量百应");
      } else if (hostname === "www.tiktok.com") {
          detectedPlatform = "tiktok";
          console.log("当前直播平台：TikTok");
          showMessage("当前直播平台：TikTok");
      } else if (hostname === "eos.douyin.com") {
          detectedPlatform = "douyin";
          console.log("当前直播平台：抖音");
          showMessage("当前直播平台：抖音");
      }

  // 定义全局对象供注入检查使用，立即设置平台信息
  window.danmakuListener = {
    status: 'initializing',
    version: '3.0',
    platform: detectedPlatform,
    socket: null,
    // 添加初始化完成方法
    markReady: function() {
      this.status = 'ready';
      console.log("danmakuListener已就绪");
      showMessage("弹幕监听器已就绪", 'success');
    },
    // 添加快速初始化方法
    quickInit: function() {
      console.log("danmakuListener快速初始化开始");
      this.status = 'ready';
      console.log("danmakuListener快速初始化完成");
    }
  };

  // 立即执行快速初始化
  window.danmakuListener.quickInit();

  // 延迟执行完整初始化过程
  setTimeout(function () {
      let my_socket = null;
      let targetNode = null;
      let my_observer = null;

      let reconnectAttempts = 0;
      const maxReconnectAttempts = 5;
      let reconnectTimeout = null;

      function connectWebSocket() {
          // 清除之前的重连定时器
          if (reconnectTimeout) {
              clearTimeout(reconnectTimeout);
              reconnectTimeout = null;
          }

          // 确保danmakuListener状态为连接中
          window.danmakuListener.status = 'connecting';

          // 创建 WebSocket 连接，适配服务端
          try {
              my_socket = new WebSocket(wsUrl);
              
              // 设置连接超时检测
              const connectionTimeout = setTimeout(() => {
                  if (my_socket.readyState === WebSocket.CONNECTING) {
                      console.error("WebSocket连接超时");
                      my_socket.close();
                      scheduleReconnect();
                  }
              }, 10000); // 10秒连接超时

              my_socket.addEventListener("open", (event) => {
                  clearTimeout(connectionTimeout);
                  console.log("ws连接打开");
                  showMessage("WebSocket连接已建立", 'success');
                  window.danmakuListener.socket = my_socket;
                  window.danmakuListener.status = 'connected';
                  reconnectAttempts = 0; // 重置重连计数

                  // 向服务器发送一条消息
                  const data = {
                      type: "info",
                      content: "ws连接成功",
                  };
                  console.log(data);
                  try {
                      my_socket.send(JSON.stringify(data));
                  } catch (error) {
                      console.error("发送消息失败:", error);
                  }
              });

          } catch (error) {
              console.error("创建WebSocket连接失败:", error);
              window.danmakuListener.status = 'failed';
              scheduleReconnect();
              return;
          }

          // 当收到消息时触发
          my_socket.addEventListener("message", (event) => {
              console.log("收到服务器数据:", event.data);
              // 只在控制台显示弹幕数据，不在页面弹出消息框
              // showMessage("收到服务器数据: " + event.data);
          });

          // 当连接出错时触发
          my_socket.addEventListener("error", (event) => {
              console.error("WebSocket连接错误:", event);
              showMessage("WebSocket连接错误: " + (event.message || "未知错误"), 'error');
          });

          // 当连接关闭时触发
          my_socket.addEventListener("close", (event) => {
              console.log("WS连接关闭, 代码:", event.code, "原因:", event.reason);
              window.danmakuListener.status = 'disconnected';
              window.danmakuListener.socket = null;
              
              // 只有在非正常关闭时才显示错误消息和重连
              if (event.code !== 1000) {
                  showMessage(`WS连接异常关闭 (代码: ${event.code}, 原因: ${event.reason || '无'})`, 'error');
                  scheduleReconnect();
              } else {
                  console.log("WebSocket正常关闭");
              }
          });
      }

      function scheduleReconnect() {
          if (reconnectAttempts >= maxReconnectAttempts) {
              console.error(`WebSocket重连失败，已达到最大重试次数 ${maxReconnectAttempts}`);
              showMessage(`WebSocket连接失败，已停止重试`, 'error');
              window.danmakuListener.status = 'failed';
              return;
          }

          reconnectAttempts++;
          const delay = Math.min(1000 * Math.pow(2, reconnectAttempts - 1), 30000); // 指数退避，最大30秒
          console.log(`WebSocket将在 ${delay}ms 后进行第 ${reconnectAttempts} 次重连...`);
          
          reconnectTimeout = setTimeout(() => {
              console.log(`尝试第 ${reconnectAttempts} 次重新连接WebSocket...`);
              connectWebSocket();
          }, delay);
      }

      if (hostname != "buyin.jinritemai.com") {
          // 初始连接
          connectWebSocket();
      }

      // 配置观察选项
      const config = {
          childList: true,
          subtree: true,
      };

      let timeoutId = null; // 定时器ID
      let cycleTimeoutId = null; // 循环周期定时器ID

      // 创建配置界面
      function createConfigUI() {
          const configDiv = document.createElement('div');
          configDiv.style.cssText = `
              position: fixed;
              bottom: 20px;
              right: 20px;
              background: #ffffff80;
              border-radius: 8px;
              box-shadow: 0 2px 12px 0 rgba(0,0,0,.1);
              padding: 15px;
              z-index: 1000;
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
          `;

          configDiv.innerHTML = `
              <button id="toggleConfig" style="
                  width: 100%;
                  padding: 8px 15px;
                  background: #409EFF;
                  color: white;
                  border: none;
                  border-radius: 4px;
                  cursor: pointer;
                  font-size: 14px;
                  transition: background-color 0.3s;
              ">展开配置</button>
              <div id="configPanel" style="
                  display: none;
                  margin-top: 10px;
              ">
                  <!-- WS监听配置 -->
                  <div style="
                      margin-bottom: 20px;
                      padding: 15px;
                      border: 1px solid #DCDFE6;
                      border-radius: 4px;
                      background: #F5F7FA;
                  ">
                      <h3 style="
                          margin: 0 0 15px 0;
                          color: #303133;
                          font-size: 16px;
                          font-weight: 500;
                      ">WS监听配置</h3>
                      <div style="margin-bottom: 15px;">
                          <label style="display: block; margin-bottom: 5px; color: #606266; font-size: 14px;">
                              WebSocket 地址:
                          </label>
                          <input type="text" id="wsUrl" value="${wsUrl}" style="
                              width: 100%;
                              padding: 8px;
                              border: 1px solid #DCDFE6;
                              border-radius: 4px;
                              box-sizing: border-box;
                              font-size: 14px;
                              transition: border-color 0.3s;
                          "/>
                      </div>
                      <button id="saveConfig" style="
                          width: 100%;
                          padding: 8px 15px;
                          background: #409EFF;
                          color: white;
                          border: none;
                          border-radius: 4px;
                          cursor: pointer;
                          font-size: 14px;
                          transition: background-color 0.3s;
                      ">保存WS配置</button>
                  </div>

                  <!-- 商品弹窗配置 -->
                  <div style="
                      padding: 15px;
                      border: 1px solid #DCDFE6;
                      border-radius: 4px;
                      background: #F5F7FA;
                  ">
                      <h3 style="
                          margin: 0 0 15px 0;
                          color: #303133;
                          font-size: 16px;
                          font-weight: 500;
                      ">商品弹窗配置</h3>
                      <div style="margin-bottom: 15px;">
                          <label style="display: block; margin-bottom: 5px; color: #606266; font-size: 14px;">
                              商品编号 (空格分隔):
                          </label>
                          <input type="text" id="itemIndices" style="
                              width: 100%;
                              padding: 8px;
                              border: 1px solid #DCDFE6;
                              border-radius: 4px;
                              box-sizing: border-box;
                              font-size: 14px;
                              transition: border-color 0.3s;
                          "/>
                      </div>
                      <div style="margin-bottom: 15px;">
                          <label style="display: block; margin-bottom: 5px; color: #606266; font-size: 14px;">
                              每次触发延迟 (毫秒):
                          </label>
                          <input type="number" id="delay" value="5000" style="
                              width: 100%;
                              padding: 8px;
                              border: 1px solid #DCDFE6;
                              border-radius: 4px;
                              box-sizing: border-box;
                              font-size: 14px;
                              transition: border-color 0.3s;
                          "/>
                      </div>
                      <div style="margin-bottom: 15px;">
                          <label style="display: block; margin-bottom: 5px; color: #606266; font-size: 14px;">
                              循环周期延迟 (毫秒):
                          </label>
                          <input type="number" id="cycleDelay" value="5000" style="
                              width: 100%;
                              padding: 8px;
                              border: 1px solid #DCDFE6;
                              border-radius: 4px;
                              box-sizing: border-box;
                              font-size: 14px;
                              transition: border-color 0.3s;
                          "/>
                      </div>
                      <button id="applyConfig" style="
                          width: 100%;
                          padding: 8px 15px;
                          background: #67C23A;
                          color: white;
                          border: none;
                          border-radius: 4px;
                          cursor: pointer;
                          font-size: 14px;
                          transition: background-color 0.3s;
                      ">启动自动弹窗</button>
                  </div>
              </div>
          `;
          document.body.appendChild(configDiv);

          // 添加悬停效果
          const buttons = configDiv.getElementsByTagName('button');
          for (let button of buttons) {
              button.addEventListener('mouseover', function() {
                  this.style.opacity = '0.8';
              });
              button.addEventListener('mouseout', function() {
                  this.style.opacity = '1';
              });
          }

          // 添加输入框焦点效果
          const inputs = configDiv.getElementsByTagName('input');
          for (let input of inputs) {
              input.addEventListener('focus', function() {
                  this.style.borderColor = '#409EFF';
              });
              input.addEventListener('blur', function() {
                  this.style.borderColor = '#DCDFE6';
              });
          }

          document.getElementById('toggleConfig').addEventListener('click', () => {
              const configPanel = document.getElementById('configPanel');
              configPanel.style.display = configPanel.style.display === 'none' ? 'block' : 'none';
          });

          document.getElementById('applyConfig').addEventListener('click', applyConfig);
          document.getElementById('saveConfig').addEventListener('click', saveConfig);
      }

      // 保存监听配置
      function saveConfig() {
          const newWsUrl = document.getElementById('wsUrl').value;

          // 检查WebSocket地址格式
          if (!newWsUrl.startsWith('ws://') && !newWsUrl.startsWith('wss://')) {
              showMessage('WebSocket地址格式错误，必须以ws://或wss://开头', 'error');
              return;
          }

          try {
              new URL(newWsUrl);
              wsUrl = newWsUrl; // 更新 WebSocket 地址
              showMessage('配置保存成功', 'success');
          } catch (error) {
              showMessage('WebSocket地址格式无效', 'error');
          }
      }

      // 应用配置
      function applyConfig() {
          const itemIndicesInput = document.getElementById('itemIndices').value;
          if (!itemIndicesInput.trim()) {
              showMessage('请输入商品编号', 'warning');
              return;
          }

          const delay = parseInt(document.getElementById('delay').value, 10);
          const cycleDelay = parseInt(document.getElementById('cycleDelay').value, 10);

          // 验证延迟时间
          if (delay < 0 || isNaN(delay)) {
              showMessage('触发延迟时间必须大于0', 'warning');
              return;
          }
          if (cycleDelay < 0 || isNaN(cycleDelay)) {
              showMessage('循环周期延迟时间必须大于0', 'warning');
              return;
          }

          const itemIndices = itemIndicesInput.split(' ')
              .filter(str => str.trim() !== '')
              .map(str => parseInt(str.trim(), 10));

          // 验证商品编号
          if (itemIndices.some(index => isNaN(index) || index <= 0)) {
              showMessage('商品编号必须为正整数', 'warning');
              return;
          }

          const applyBtn = document.getElementById('applyConfig');
          const isRunning = applyBtn.textContent === '停止自动弹窗';

          if (isRunning) {
              // 如果当前正在运行,则停止
              stopLoop();
              applyBtn.textContent = '启动自动弹窗';
              applyBtn.style.backgroundColor = '#67C23A';
              showMessage('自动弹窗已停止', 'info');
          } else {
              // 如果当前已停止,则启动
              startLoop(itemIndices, delay, cycleDelay);
              applyBtn.textContent = '停止自动弹窗';
              applyBtn.style.backgroundColor = '#F56C6C';
              showMessage('自动弹窗已启动', 'success');
          }
      }

      // 启动循环
      function startLoop(itemIndices, delay, cycleDelay) {
          if (itemIndices.length === 0) return;

          const triggerNext = (index = 0) => {
              if (index >= itemIndices.length) {
                  // 结束一轮后等待循环周期延迟再开始下一轮
                  cycleTimeoutId = setTimeout(() => triggerNext(0), cycleDelay);
                  return;
              }

              const itemIndex = itemIndices[index] - 1;
              if (isNaN(itemIndex) || itemIndex < 0) {
                  console.error(`商品编号 ${itemIndex + 1} 无效`);
                  triggerNext(index + 1);
                  return;
              }
              const buttonIndex = 3 + 6 * itemIndex;

              try {
                  const buttons = document.getElementsByClassName("lvc2-grey-btn");
                  if(buttons[buttonIndex]) {
                      buttons[buttonIndex].click();
                      console.log(`已触发商品编号 ${itemIndex + 1} 的弹窗`);
                  } else {
                      console.error("无法找到指定的按钮！");
                  }
              } catch (error) {
                  console.error("触发弹窗时发生错误：", error);
              }

              timeoutId = setTimeout(() => triggerNext(index + 1), delay);
          };

          triggerNext();
      }

      // 停止循环
      function stopLoop() {
          if (timeoutId !== null) {
              clearTimeout(timeoutId);
              timeoutId = null;
          }
          if (cycleTimeoutId !== null) {
              clearTimeout(cycleTimeoutId);
              cycleTimeoutId = null;
          }
      }

      // 巨量百应
      if (hostname === "buyin.jinritemai.com") {
          // 初始化
          createConfigUI();
      }

      // 添加重试观察的函数，支持最大重试次数和指数退避
      let observeRetryCount = 0;
      const maxObserveRetries = 50; // 最大重试次数
      const baseRetryDelay = 10000; // 基础重试延迟时间(ms)

      // 格式化并发送消息到WebSocket服务器
      function sendFormattedMessage(msg) {
          if (!msg.username) {
              // 必须有用户名才能发送
              return;
          }

          let data = {
              type: msg.type,
              platform: msg.platform,
              username: msg.username,
          };

          let logContent = '';

          switch (msg.type) {
              case 'comment':
                  data.content = msg.content || '';
                  logContent = data.content;
                  break;
              case 'gift':
                  data.gift_name = msg.additionalData.gift_name || msg.content || '';
                  data.price = msg.additionalData.price || 0;
                  logContent = `送出 ${data.gift_name}`;
                  break;
              case 'entrance':
                  logContent = '进入直播间';
                  // spec has no content field
                  break;
              case 'follow':
                  logContent = '关注了主播';
                  // spec has no content field
                  break;

              case 'like':
                  logContent = '点了个赞';
                  // spec has no content field
                  break;
              case 'super_chat':
                  data.content = msg.content || '';
                  data.price = msg.additionalData.price || 0;
                  logContent = `发送SC: ${data.content}`;
                  break;
              default:
                  data.content = msg.content || '';
                  logContent = data.content;
                  if(msg.additionalData) {
                      data.data = msg.additionalData;
                  }
                  break;
          }

          // 根据消息类型显示不同类型的提示
          let messageIcon, messageColor;
          if (msg.type === "gift") {
              messageIcon = "[礼物]";
              messageColor = "success";
          } else if (msg.type === "like") {
              messageIcon = "[点赞]";
              messageColor = "info";
          } else if (msg.type === "entrance") {
              messageIcon = "[入场]";
              messageColor = "info";
          } else if (msg.type === "super_chat") {
              messageIcon = "[SC]";
              messageColor = "warning";
          } else if (msg.type === "comment") {
              messageIcon = "[弹幕]";
              messageColor = "info";
          } else if (msg.type === "follow") {
              messageIcon = "[关注]";
              messageColor = "info";
          }

          const logMessage = `${msg.username}: ${logContent}`;
          console.log(`${logMessage} (${msg.type})`);
          showMessage(`${messageIcon} ${logMessage}`, messageColor);

          if (my_socket && my_socket.readyState === WebSocket.OPEN) {
              my_socket.send(JSON.stringify(data));
          }
      }

      // 初始化观察器和目标节点
      function initObserver() {
          // 清理之前的资源
          if (my_observer) {
              try {
                  my_observer.disconnect();
              } catch (e) {
                  console.error("断开旧观察器连接失败:", e);
              }
          }

          if (my_socket && hostname != "buyin.jinritemai.com") {
              try {
                  my_socket.close();
              } catch (e) {
                  console.error("关闭旧WebSocket连接失败:", e);
              }
              // 重新连接WebSocket
              connectWebSocket();
          }

          // 重置变量
          my_observer = null;
          targetNode = null;

          // 根据平台初始化对应的目标节点和观察器
          const platformConfig = {
              "www.douyu.com": {
                  selector: ".Barrage-list",
              },
              "live.kuaishou.com": {
                  selector: ".chat-history"
              },
              "mobile.yangkeduo.com": {
                  selector: ".MYFlHgGu"
              },
              "live.1688.com": {
                  selector: ".pc-living-room-message"
              },
              "tbzb.taobao.com": {
                  selector: "#liveComment"
              },
              "redlive.xiaohongshu.com": {
                  selector: ".comments"
              },
              "ark.xiaohongshu.com": {
                  selector: ".comments"
              },
              "channels.weixin.qq.com": {
                  // 监听一个更上层的节点来捕获包括入场在内的所有消息
                  selector: ".live-realtime-interactive-part"
              },
              "buyin.jinritemai.com": {
                  selector: "#comment-list-wrapper"
              },
              "www.tiktok.com": {
                  selector: ".flex-1"
              },
              "eos.douyin.com": {
                  selector: ".list-gdqoHn"
              }
          };

          // 获取当前平台配置
          const platform = platformConfig[hostname] ||
                           (hostname === "ark.xiaohongshu.com" ? platformConfig["redlive.xiaohongshu.com"] : null);

          if (!platform) {
              console.error("未知平台:", hostname);
              return false;
          }

          // 获取目标节点
          if (hostname === "channels.weixin.qq.com") {
              // 微信视频号弹幕区域位于 wujie-app 的 shadow DOM 内，需从 shadowRoot 中查询
              try {
                  const wujie = document.querySelector("wujie-app");
                  if (wujie && wujie.shadowRoot) {
                      targetNode = wujie.shadowRoot.querySelector(platform.selector);
                  } else {
                      targetNode = document.querySelector(platform.selector);
                  }
              } catch (e) {
                  console.warn("微信视频号 shadowRoot 查询异常，回退到普通查询:", e);
                  targetNode = document.querySelector(platform.selector);
              }
          } else {
              targetNode = document.querySelector(platform.selector);
          }
          if (!targetNode) {
              console.warn("未找到目标DOM节点，可能页面未完全加载");
              return false;
          }

          // 创建观察器实例
          my_observer = new MutationObserver((mutations) => {
              mutations.forEach((mutation) => {
                  if (mutation.type === "childList") {
                      mutation.addedNodes.forEach((node) => {
                          processDanmaku(node);
                      });
                  }
              });
          });

          return true;
      }

      // 处理弹幕消息的通用函数
      function processDanmaku(node) {
          try {
              if (!node || node.nodeType !== Node.ELEMENT_NODE) return;

              // 根据不同平台解析弹幕内容
              if (hostname === "www.douyu.com" && node.classList.contains("Barrage-listItem")) {
                  const usernameElement = node.querySelector(".Barrage-nickName");
                  const contentElement = node.querySelector(".Barrage-content");
                  if (usernameElement && contentElement) {
                      const username = usernameElement.textContent.trim().slice(0, -1);
                      const content = contentElement.textContent.trim();
                      sendFormattedMessage({ type: 'comment', username, content, platform: detectedPlatform });
                  }
              } else if (hostname === "live.kuaishou.com" && node.querySelector(".comment-cell")) {
                  const commentCells = node.querySelectorAll(".comment-cell");
                  commentCells.forEach((cell) => {
                      const usernameElement = cell.querySelector(".username");
                      if (!usernameElement) return;

                      const username = usernameElement.textContent.trim().replace("：", "");
                      const giftCommentElement = cell.querySelector(".gift-comment");
                      const likeElement = cell.querySelector(".like");
                      const commentElement = cell.querySelector(".comment");

                      if (giftCommentElement) {
                          const content = giftCommentElement.textContent.trim();
                          sendFormattedMessage({ type: 'gift', username, content, platform: detectedPlatform, additionalData: { gift_name: content } });
                      } else if (likeElement) {
                          sendFormattedMessage({ type: 'like', username, platform: detectedPlatform });
                      } else if (commentElement) {
                          const extractContent = (element) => {
                              let text = "";
                              element.childNodes.forEach((child) => {
                                  if (child.nodeType === Node.TEXT_NODE) {
                                      text += child.textContent.trim();
                                  } else if (child.nodeType === Node.ELEMENT_NODE && child.tagName === "IMG" && child.classList.contains("emoji")) {
                                      text += child.getAttribute("alt") || "[表情]";
                                  }
                              });
                              return text;
                          };
                          const content = extractContent(commentElement);
                          sendFormattedMessage({ type: 'comment', username, content, platform: detectedPlatform });
                      }
                  });
              } else if (hostname === "mobile.yangkeduo.com" && node.classList.contains("_24Qh0Jmi")) {
                  const usernameElement = node.querySelector(".t6fCgSnz");
                  const contentElement = node.querySelector("._16_fPXYP");
                  if (usernameElement && contentElement) {
                      const username = usernameElement.textContent.trim().slice(0, -1);
                      const content = contentElement.textContent.trim();
                      sendFormattedMessage({ type: 'comment', username, content, platform: detectedPlatform });
                  }
              } else if (hostname === "live.1688.com" && node.classList.contains("comment-message")) {
                  const usernameElement = node.querySelector(".from");
                  const contentElement = node.querySelector(".msg-text");
                  if (usernameElement && contentElement) {
                      const username = usernameElement.textContent.trim().slice(0, -1);
                      const content = contentElement.textContent.trim();
                      sendFormattedMessage({ type: 'comment', username, content, platform: detectedPlatform });
                  }
              } else if (hostname === "tbzb.taobao.com" && node.classList.contains("itemWrap--EcN_tFIg")) {
                  const usernameElement = node.querySelector(".authorTitle--_Dl75ZJ6");
                  const contentElement = node.querySelector(".content--pSjaTkyl");
                  if (usernameElement && contentElement) {
                      const username = usernameElement.textContent.trim().slice(0, -1);
                      const content = contentElement.textContent.trim();
                      sendFormattedMessage({ type: 'comment', username, content, platform: detectedPlatform });
                  }
              } else if ((hostname === "redlive.xiaohongshu.com" || hostname === "ark.xiaohongshu.com") && node.classList.contains("comment-list-item")) {
                  const spans = node.getElementsByTagName("span");
                  let username = '', content = '';
                  if (spans.length >= 2) {
                      username = spans[spans.length - 2].textContent.trim().slice(0, -1);
                      content = spans[spans.length - 1].textContent.trim();
                      sendFormattedMessage({ type: 'comment', username, content, platform: detectedPlatform });
                  }
              } else if (hostname === "channels.weixin.qq.com") {
                  // 只处理常规消息 (弹幕, 礼物, 点赞) - 入场信息由专门的监听器处理
                  const messageViews = node.querySelectorAll ? Array.from(node.querySelectorAll('.vue-recycle-scroller__item-view')) : [];
                  if (node.matches && node.matches('.vue-recycle-scroller__item-view')) {
                      messageViews.push(node);
                  }
                  messageViews.forEach(container => {
                      const usernameElement = container.querySelector(".message-username-desc");
                      const contentElement = container.querySelector(".message-content");
                      if (!usernameElement || !contentElement) return;

                      const username = usernameElement.textContent.trim().replace(/[：:]/g, '').trim();
                      const content = contentElement.textContent.trim();
                      let messageType = "comment";
                      let additionalData = {};

                      const messageTypeElement = container.querySelector(".message-type");
                      if (messageTypeElement) {
                          const messageTypeText = messageTypeElement.textContent.trim();
                          if (messageTypeText.includes("礼物")) {
                              messageType = "gift";
                              additionalData.gift_name = content;
                          } else if (messageTypeText.includes("点赞")) {
                              messageType = "like";
                          }
                      }
                      sendFormattedMessage({ type: messageType, username, content, platform: detectedPlatform, additionalData });
                  });
              } else if (hostname === "buyin.jinritemai.com" && node.classList.contains("commentItem-AzWZJ8")) {
                  const nicknameDiv = node.querySelector(".nickname-H277c7");
                  const descriptionDiv = node.querySelector(".description-ml2w_d");
                  if (nicknameDiv && descriptionDiv) {
                      let username = '';
                      nicknameDiv.childNodes.forEach(n => { if (n.nodeType === Node.TEXT_NODE) username += n.textContent; });
                      username = username.trim().replace(/：$/, '');
                      const content = descriptionDiv.textContent.trim();
                      sendFormattedMessage({ type: 'comment', username, content, platform: detectedPlatform });
                  }
              } else if (hostname === "www.tiktok.com" && node.classList.contains("break-words")) {
                  const nicknameDiv = node.querySelector(".truncate");
                  const commentDiv = node.querySelector(".align-middle");
                  if (nicknameDiv && commentDiv) {
                      let username = '';
                      nicknameDiv.childNodes.forEach(n => { if (n.nodeType === Node.TEXT_NODE) username += n.textContent; });
                      const content = commentDiv.textContent.trim();
                      sendFormattedMessage({ type: 'comment', username: username.trim(), content, platform: detectedPlatform });
                  }
              } else if (hostname === "eos.douyin.com" && node.classList.contains("item-x_bazm")) {
                  const usernameElement = node.querySelector(".item-name-qalgHb");
                  const contentElement = node.querySelector(".item-content-kHjdRK");
                  if (usernameElement && contentElement) {
                      const username = usernameElement.textContent.trim().slice(0, -1);
                      const content = contentElement.textContent.trim();
                      sendFormattedMessage({ type: 'comment', username, content, platform: detectedPlatform });
                  }
              }
          } catch (error) {
              console.error("处理弹幕时出错:", error);
          }
      }

      function retryObserve() {
          try {
              // 尝试初始化观察器和目标节点
              if (!targetNode || !my_observer) {
                  console.log("初始化观察所需变量...");
                  
                  // 针对微信视频号添加特殊调试信息
                  if (hostname === "channels.weixin.qq.com") {
                      console.log("微信视频号平台检测到，查找弹幕容器(含shadowRoot)...");
                      try {
                          const wujie = document.querySelector("wujie-app");
                          if (wujie && wujie.shadowRoot) {
                              const nodes = wujie.shadowRoot.querySelectorAll(".vue-recycle-scroller, .vue-recycle-scroller__item-wrapper, .vue-recycle-scroller__item-view");
                              console.log(`在 wujie-app.shadowRoot 中找到 ${nodes.length} 个相关元素`);
                              nodes.forEach((el, index) => {
                                  console.log(`元素 ${index}:`, el.className, el);
                              });
                          } else {
                              console.log("未找到 wujie-app 或其 shadowRoot，回退至 document 查询...");
                              const debugElements = document.querySelectorAll(".vue-recycle-scroller, .vue-recycle-scroller__item-wrapper, .vue-recycle-scroller__item-view");
                              console.log(`document 中找到 ${debugElements.length} 个相关元素`);
                              debugElements.forEach((el, index) => {
                                  console.log(`元素 ${index}:`, el.className, el);
                              });
                          }
                      } catch (e) {
                          console.warn("微信视频号调试查询异常:", e);
                      }
                  }
                  
                  if (!initObserver()) {
                      throw new Error("初始化失败，将在延迟后重试");
                  }
              }

              // 开始观察
              my_observer.observe(targetNode, config);

              // 重置重试计数
              observeRetryCount = 0;
              console.log("观察成功启动！");
              showMessage("观察成功启动！", 'success');
              
              // 更新状态为active并标记为ready
              window.danmakuListener.status = 'active';
              window.danmakuListener.markReady();
              console.log("弹幕监听器状态已更新为: active");
          } catch (error) {
              console.error("观察失败:", error);
              showMessage("观察失败: " + error.message, 'error');

              // 增加重试计数
              observeRetryCount++;

              if (observeRetryCount <= maxObserveRetries) {
                  // 使用更平滑的指数退避
                  const retryDelay = Math.min(
                      baseRetryDelay * (1 + (observeRetryCount - 1) * 0.5),
                      30000 // 最大延迟不超过30秒
                  );

                  console.log(`第${observeRetryCount}次重试失败，${retryDelay/1000}秒后将再次尝试...`);
                  showMessage(`第${observeRetryCount}次重试失败，${retryDelay/1000}秒后将再次尝试...`, 'warning');

                  setTimeout(retryObserve, retryDelay);
              } else {
                  console.error(`已达到最大重试次数(${maxObserveRetries})，观察启动失败！`);
                  showMessage(`已达到最大重试次数(${maxObserveRetries})，观察启动失败！如需继续，请刷新页面重试。`, 'error');
              }
          }
      }

      // 微信视频号入场信息监听 - 重新设计
      if (hostname === "channels.weixin.qq.com") {
          let processedUsers = new Set(); // 防重复处理
          let entranceObserver = null;
          let checkInterval = null;
          
          // 处理入场信息的函数
          function processEntranceMessage(element) {
              try {
                  // 查找nickname元素的多种可能路径
                  let nicknameElement = element.querySelector('span.nickname') || 
                                      element.querySelector('.nickname') ||
                                      element.querySelector('span[data-v-2297997e]');
                  
                  // 如果当前元素本身就是nickname
                  if (!nicknameElement && (element.classList.contains('nickname') || element.hasAttribute('data-v-2297997e'))) {
                      nicknameElement = element;
                  }
                  
                  if (nicknameElement) {
                      const username = nicknameElement.textContent.trim();
                      if (username && !processedUsers.has(username)) {
                          processedUsers.add(username);
                          sendFormattedMessage({ type: 'entrance', username, platform: detectedPlatform });
                          console.log("[微信视频号] 检测到入场用户:", username);
                          return true;
                      }
                  }
              } catch (error) {
                  console.error("处理入场信息时出错:", error);
              }
              return false;
          }
          
          // MutationObserver回调
          function handleEntranceMutations(mutations) {
              mutations.forEach((mutation) => {
                  if (mutation.type === 'childList') {
                      mutation.addedNodes.forEach((node) => {
                          if (node.nodeType === Node.ELEMENT_NODE) {
                              // 检查新增节点是否包含入场信息
                              if (node.classList.contains('live-join-message') || 
                                  node.querySelector('.live-join-message') ||
                                  node.classList.contains('nickname') ||
                                  node.querySelector('.nickname')) {
                                  processEntranceMessage(node);
                              }
                              
                              // 递归检查子节点
                              const nicknameElements = node.querySelectorAll('.nickname, span[data-v-2297997e]');
                              nicknameElements.forEach(processEntranceMessage);
                          }
                      });
                  }
                  
                  // 监听属性变化（如显示/隐藏）
                  if (mutation.type === 'attributes' && 
                      (mutation.attributeName === 'style' || mutation.attributeName === 'class')) {
                      const target = mutation.target;
                      if (target.nodeType === Node.ELEMENT_NODE) {
                          processEntranceMessage(target);
                      }
                  }
              });
          }
          
          // 定时检查函数
          function checkForEntranceMessages() {
              try {
                  const wujie = document.querySelector("wujie-app");
                  if (wujie && wujie.shadowRoot) {
                      // 使用完整的DOM路径查找入场信息
                      const entranceContainer = wujie.shadowRoot.querySelector(
                          "#container-wrap > div.container-center > div > div > div > div.live-message-container > div.live-join-message-container"
                      );
                      
                      if (entranceContainer) {
                          // 查找所有可能的nickname元素
                          const nicknameElements = entranceContainer.querySelectorAll('.nickname, span[data-v-2297997e]');
                          nicknameElements.forEach(processEntranceMessage);
                      }
                      
                      // 也检查可能的入场消息元素
                      const joinMessages = wujie.shadowRoot.querySelectorAll('.live-join-message');
                      joinMessages.forEach(processEntranceMessage);
                  }
              } catch (error) {
                  console.error("定时检查入场信息时出错:", error);
              }
          }
          
          // 初始化监听
          function initEntranceListener() {
              try {
                  const wujie = document.querySelector("wujie-app");
                  if (wujie && wujie.shadowRoot) {
                      // 监听整个消息容器
                      const messageContainer = wujie.shadowRoot.querySelector(
                          "#container-wrap > div.container-center > div > div > div > div.live-message-container"
                      );
                      
                      if (messageContainer) {
                          entranceObserver = new MutationObserver(handleEntranceMutations);
                          entranceObserver.observe(messageContainer, {
                              childList: true,
                              subtree: true,
                              attributes: true,
                              attributeFilter: ['style', 'class']
                          });
                          console.log("[微信视频号] 入场信息MutationObserver已启动");
                      }
                      
                      // 启动定时检查（每2秒检查一次）
                      checkInterval = setInterval(checkForEntranceMessages, 2000);
                      console.log("[微信视频号] 入场信息定时检查已启动");
                      
                      // 立即执行一次检查
                      checkForEntranceMessages();
                      
                      // 5分钟后停止定时检查以节省资源
                      setTimeout(() => {
                          if (checkInterval) {
                              clearInterval(checkInterval);
                              checkInterval = null;
                              console.log("[微信视频号] 定时检查已停止（5分钟后自动停止）");
                          }
                      }, 300000);
                      
                  } else {
                      console.warn("[微信视频号] 未找到 wujie-app 或其 shadowRoot");
                  }
              } catch (error) {
                  console.error("[微信视频号] 入场信息监听初始化失败:", error);
              }
          }
          
          // 延迟初始化，确保DOM完全加载
          setTimeout(initEntranceListener, 2000);
      }

      // 初始化观察
      retryObserve();

  }, 10000);
})();
