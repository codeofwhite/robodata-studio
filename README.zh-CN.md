# RoboData Studio · by IPPLab

[English](README.md) | [简体中文](README.zh-CN.md)

面向机器人仿真示范数据的采集、审核与导出工具。

**采集 → 校验 → QA → 导出 → 实际读取。** 原始 Episode 保持不变，QA 决定存于索引，
训练格式由原始记录重建。本仓库以新的初始提交发布源码快照，参考采集路径为
Isaac Panda `rigid_cube_lift`、PhysX 与 Keyboard/GELLO 输入。
物理 GELLO、真机操作和抓取成功率没有经过本版本验证。

## 组成

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| Studio UI | `app/`、`components/` | 会话、审核、导出工作流 |
| Studio API | `backend/` | SQLite 索引、QA、独立 worker 和导出任务 |
| 公共协议包 | `packages/robot-data-contracts/` | Canonical Episode v1、writer、reader、校验 |
| GELLO Remote | `teleop/` | 输入协议、安全过滤、仿真 worker 和控制台源码 |

Python 导入名保留。API、模拟器和 LeRobot 使用分离环境。布料、生成、资产等扩展默认
关闭；源码里存在扩展实现不表示已经支持或验收它们。

## 启动 UI 和 API

需要 Python 3.12+、Node.js 22.13+。请使用完整 checkout，backend 构建需要相邻的
config 文件。在仓库根目录执行：

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/python -m pip install ./packages/robot-data-contracts ./teleop './backend[dev]'
# 先检查模板；已有本机配置时保留。
test -f .env || cp .env.example .env
set -a
source .env
set +a
backend/.venv/bin/python -m uvicorn robot_data_studio.main:app --host 127.0.0.1 --port 8010
```

另一个终端在同一仓库执行：

```bash
npm ci --no-audit --no-fund
npm run build
npm run start -- --hostname 127.0.0.1 --port 3000
```

打开 `http://127.0.0.1:3000`，API 文档在 `http://127.0.0.1:8010/docs`。
开发模式用 `npm run dev -- --host 127.0.0.1`；API 地址改变时，在构建前设置
`NEXT_PUBLIC_STUDIO_API`。本地构建不要求 Sites/Cloudflare 账户或托管元数据。

UI/API 不需要模拟器即可启动；采集需要另行配置兼容 SDK、机器人资产、明确的 GPU
与 worker 环境，详见[安装与配置](docs/INSTALLATION.md)。

## Collector 控制台与外部依赖

**公开快照不分发包含 NVIDIA 库的预编译 WebRTC 控制台。** worker 的 WebSocket 协议
与录制逻辑保留；尚未本地构建时，Collector 根页面返回 `Web console is not built`。
请先核对适用 NVIDIA 条款，再按安装指南在自己的环境构建 `teleop/web_console/`。

本仓库不含仿真 SDK、机器人 USD、旧部署资产包、权重、相机序列号、采集数据或内部实验目录。
公开配置的相机参数为 nominal，不能作为实物标定。

## 验证范围

[验证记录](docs/VALIDATION.md)区分当前公开快照的检查和此前候选的 100 帧 Isaac
采集 → QA → LeRobot 读取。此前轨迹由 agent 发送 Keyboard 消息采集，抓取任务失败；
数据完整性通过不代表任务成功、真人遥操或硬件验证。临时 HTTP 测试夹具不等于实际
NVIDIA 控制台构建或视频流验收。

## IPPLab 工具系列

统一使用 **by IPPLab** 署名。RoboData Studio 是首个发布条目；SceneKit（场景）和
DataAugment（增强）是路线名称，尚不表示已经发布。GELLO Remote 与公共协议包暂随
本仓库维护，见[系列路线](docs/ECOSYSTEM.md)与[架构](docs/ARCHITECTURE.md)。

## 许可证

贡献者有权授权的自有代码采用 [Apache-2.0](LICENSE)，署名及第三方例外见
[NOTICE](NOTICE)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。SDK、资产和第三方
内容保留各自条款，公开可下载不自动等于允许再分发，见[资产边界](docs/LICENSES_AND_ASSETS.md)。
