# BHB-EEG Station

基于 Windows 11 的 Web 上位机：负责 EEG 采集控制、阻抗检测、离线录制与导出（CSV/EDF）、以及浏览器端实时可视化。

***

## 1. 快速开始

### 1.1 环境要求

- Windows 11（建议使用管理员权限运行一次以完成蓝牙/防火墙授权）
- Python 3.10.20（建议保持一致）

### 1.2 安装依赖

在项目根目录执行：

```bash
conda env create -f environment.yml
conda activate BHB
```

### 1.3 启动后端 + 打开网页

1. 启动后端（项目根目录）：

```bash
python main.py
```

1. 浏览器打开（默认地址）：

- `http://127.0.0.1:8001/`

说明：

- 端口与监听地址由 `configs/config.yaml -> server.host/server.port` 控制。
- 前端为静态资源，由后端挂载 `web/` 目录，无需单独构建与启动前端服务。

***

## 2. 使用操作说明

### 2.1 设备页

设备页包含两部分：蓝牙连接与 EEG 通道选择。只有当“蓝牙已连接”且“通道选择已应用到系统”后，才会自动跳转到“模式”页。

#### A. 蓝牙连接

1. 打开网页后进入“设备”页
2. 点击“扫描设备”，在列表中选择目标设备
3. 点击“连接”

#### B. EEG 通道选择

1. 在“通道选择”区域选择 `n_channels` 个通道，并选择参考电极
2. 点击“应用到系统”
3. 当页面提示“应用成功”且蓝牙已连接后，会自动进入“模式”页

### 2.2 模式页：三种模式（EEG / 阻抗 / tDCS）

模式页提供三种模式入口。进入具体模式页后点击“开始/停止”控制运行。

#### A. EEG 采集（实时波形 + 离线保存）

1. 进入“模式”页，选择 EEG
2. 点击“开始采集”
3. 采集结束后点击“停止采集”

EEG 实时波形：

- EEG 模式开始后会通过 WebSocket 推送数据到浏览器进行实时绘制
- 若需要调整“显示窗口时长 / 渲染刷新率”等，只需修改 `configs/config.yaml -> ui.waveform.*`，它只影响展示，不影响采集完整性与离线存储

离线保存与导出：

- EEG 开始采集后会在本地创建离线会话并持续录制
- 默认存放目录：`configs/config.yaml -> offline.root_dir`（默认 `offlinedata/`）
- 停止采集后可在“数据存储/离线数据”相关页面进行导出：
  - CSV
  - EDF（可选带通滤波参数）

#### B. 阻抗检测（Impedance）

1. 进入“模式”页，选择 Impedance
2. 点击“开始检测”
3. 检测结束后点击“停止检测”

- Impedance 模式开始后会周期性刷新各通道阻抗与状态颜色
- 阈值与刷新频率在 `configs/config.yaml -> impedance.ui.*` 中配置

#### C. 电刺激（tDCS）

- tDCS 页面支持开启/停止刺激、两级指令控制（电流/缓升/稳定/缓降/报警阈值等）以及监测数据展示（输出电流、高压电压、故障状态、电量）
- 是否显示/是否可用由配置控制：`tdcs.enabled`、`tdcs.ui.show_reserved`

***

## 3. 环境与配置说明

### 3.1 配置文件

- 主配置（提交入库）：`configs/config.yaml`
- 本机覆盖（不提交）：`configs/config.local.yaml`
  - 适合放：本机端口、常用通道预设等

本机覆盖示例（仅示意，可按需增删）：

```yaml
ui:
  channel_selection:
    n_channels: 8
    channel_names:
    - P3
    - PO4
    - P7
    - PO8
    - PO7
    - P8
    - PO3
    - P4
    ref_channel_name: Pz
  channel_presets_local: []
eeg:
  n_channels: 8
  channel_names:
  - P3
  - PO4
  - P7
  - PO8
  - PO7
  - P8
  - PO3
  - P4
  ref_channel_name: Pz
```

### 3.2 常用配置项导航

- 版本展示（页面顶栏）：`app.ui_version`
- 后端监听：`server.host` / `server.port`
- 蓝牙扫描与目标设备：
  - `bluetooth.device_names`
  - `bluetooth.target_device`
  - `bluetooth.mac_address`（可选，推荐稳定使用）
- EEG：
  - `eeg.n_channels`（8/16 通道由配置选择）
  - `eeg.sampling_rate_hz`
  - `eeg.channel_names` / `eeg.ref_channel_name`
  - `eeg.lsl.stream_name`
- WebSocket 转发节流：`streaming.ws_send_fps_hz`、`streaming.buffer_size`
- 离线数据：`offline.root_dir`、`offline.export.*`、`offline.filter.*`

### 3.3 HTTP API / WebSocket 地址（排查故障用）

HTTP：

- 后端状态：`GET /api/status`
- 配置下发：`GET /api/config`

WebSocket：

- EEG 实时：`/ws/eeg`
- 阻抗：`/ws/impedance`
- 调试事件：`/ws/debug`

***

## 4. 版本号管理（提交推送前必做）

每次提交前只需要修改一处配置：`configs/config.yaml` 中的 `app.ui_version`（例如从 `1.0.1` 升级到 `1.0.2`），页面顶栏展示的版本号会自动同步更新。

***

## 5. 遇到问题解决办法

### 5.1 端口占用处理

如果启动时报端口（默认 `8001`）被占用，可按以下步骤释放端口：

1. 查看占用进程：
   `netstat -ano | findstr :8001`
2. 终止占用进程（将 `<PID>` 替换为上一步查到的进程号）：
   `taskkill /F /PID<PID>`

也可以直接在 `configs/config.local.yaml` 中修改 `server.port` 换一个端口。

### 5.2 无波形快速修复（最常见）

1. 确认后端在跑：浏览器打开 `http://127.0.0.1:8001/api/status`
2. 清理残留后端进程（最常见）：
   - `netstat -ano | findstr :8001`
   - `taskkill /F /PID <PID>`
3. 重置蓝牙服务（管理员 PowerShell）：
   `Restart-Service bthserv`
4. 重新启动后端与网页，点击“开始采集”；仍无波形则给设备断电重启后重试

### 5.3 扫描不到设备 / 连接失败

- 确认 Windows 蓝牙已打开，且设备处于可被发现/可连接状态
- 尝试关闭并重新打开蓝牙，或在“设备管理器”中禁用/启用蓝牙适配器
- 建议使用 `configs/config.local.yaml` 固定 `bluetooth.mac_address`，避免扫描波动
- 如出现频繁连接超时，优先尝试“重置蓝牙服务”：
  `Restart-Service bthserv`

### 5.4 页面打不开 / 持续转圈

- 先访问 `http://127.0.0.1:8001/api/status`，确认后端正常响应
- 如你修改过端口，访问地址需同步改为 `http://{server.host}:{server.port}/`
- 首次启动可能被防火墙拦截：允许 Python/uvicorn 的本地访问

### 5.5 pylsl 报错 / LSL 无数据

- 现象：控制台出现 `pylsl` 加载失败、或前端显示“未收到数据”
- 建议：
  1. 先排查蓝牙采集是否正常（能否开始采集、调试事件是否有持续输出）
  2. 重启后端再试（确保没有残留进程占用资源）
  3. 若为首次在该机器运行，检查是否缺少运行库（如 VC 运行时）；必要时重新安装依赖或更换 Python 版本（3.10/3.11 更稳定）

### 5.6 导出 CSV/EDF 失败

- 确认离线目录可写：`offline.root_dir`
- 确认磁盘空间充足
- 若 EDF 导出失败，先用 CSV 导出确认数据已录制，再排查 EDF 相关依赖（`pyedflib`）

