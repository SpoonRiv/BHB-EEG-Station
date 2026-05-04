## 版本号管理（提交推送前必做）

每次提交前只需要修改一处配置：`configs/config.yaml` 中的 `app.ui_version`（例如从 `1.0.1` 升级到 `1.0.2`），页面顶栏展示的版本号会自动同步更新。

## 端口占用处理

如果启动时报端口（默认 `8001`）被占用，可按以下步骤释放端口：

1. 查看占用进程：
   `netstat -ano | findstr :8001`
2. 终止占用进程（将 `<PID>` 替换为上一步查到的进程号）：
   `taskkill /F /PID <PID>`

## 无波形快速修复

1. 确认后端在跑：浏览器打开 `http://127.0.0.1:8001/api/status`
2. 清理残留后端进程（最常见）：
   - `netstat -ano | findstr :8001`
   - `taskkill /F /PID <PID>`
3. 重置蓝牙服务（管理员 PowerShell）：`Restart-Service bthserv`
4. 重新启动后端与网页，点击“开始采集”；仍无波形则给设备断电重启后重试

