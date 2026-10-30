![RoboData Studio by IPPLab：机器人仿真数据采集概念宣传图](docs/assets/robodata-studio-hero.png)

# RoboData Studio

**面向机器人示范数据的仿真优先工作台。**
采集多视角 Episode，审核数据质量，导出可追溯的机器人学习数据集。

[English](README.md) · [简体中文](README.zh-CN.md) · [安装配置](docs/INSTALLATION.md) · [技术架构](docs/ARCHITECTURE.md) · [验证记录](docs/VALIDATION.md)

**by IPPLab** · 自有代码 Apache-2.0 · 首个公开版本

## 从采集到可用数据集

机器人示范数据涉及控制信号、状态观测、多路相机和审核结果。RoboData Studio
将这些环节组织成统一流程，同时保持原始记录、QA 元数据和训练格式导出之间的清晰边界。

- **管理采集会话。** 通过 Studio 界面配置参考 Isaac Panda 任务，跟踪 worker 的运行状态。
- **接入 GELLO Remote。** 使用随仓库提供的输入协议、安全过滤与仿真 worker，由 worker 执行控制循环。
- **保留统一原始记录。** 使用版本化 `robot_data_episode` v1 保存 manifest、轨迹与相机图像，通过独立公共协议包在工具间共享。
- **先审核，再导出。** 在索引中管理 QA 决定，明确选择已接受的 Episode 进入导出任务。
- **追溯派生数据。** 导出保留来源信息、可重建的学习数据集，并通过读取检查验证结果。

参考配置为 **Isaac Panda · `rigid_cube_lift` · PhysX · Keyboard/GELLO 协议**。
已验证范围见下方[版本验证](#版本验证)。

## 数据工作流

![六阶段数据流程：采集、保存原始 Episode、校验、QA 审核、导出及实际读取](docs/assets/workflow.svg)

原始 Episode 保持不变，扫描后以 pending 状态进入索引，由 QA 接受状态控制导出资格。
操作者判断、自动评估结果与数据质量接受状态分别记录，因此任务失败的轨迹仍可作为
有效原始记录保留，而不会被标成任务成功。

导出记录来源和明确的动作、夹爪语义。LeRobot 读取检查验证产物；策略训练作为独立流程开展。

## 技术架构

![技术架构：Studio UI、API、SQLite 索引、GELLO Remote worker、仿真环境、公共协议包与导出环境](docs/assets/architecture.svg)

| 组件 | 职责 | 源码 |
| --- | --- | --- |
| Studio UI | 会话、Episode 审核与导出操作 | [`app/`](app/)、[`components/`](components/) |
| Studio API | 索引、QA、任务与 worker 生命周期管理 | [`backend/`](backend/) |
| GELLO Remote | 输入所有权、安全检查、仿真控制与录制 | [`teleop/`](teleop/) |
| Robot Data Contracts | 版本化 schema、writer、reader 与校验 | [`packages/robot-data-contracts/`](packages/robot-data-contracts/) |
| 导出环境 | 通过显式指定的解释器完成训练格式转换 | [配置说明](docs/INSTALLATION.md#lerobot-export) |

API、模拟器与 LeRobot 使用分离环境。控制循环由 worker 负责，公共协议包不依赖
模拟器 SDK 或数据库。组件之间的接口与数据边界见[架构文档](docs/ARCHITECTURE.md)。

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


## 版本验证

| 范围 | 已有证据 |
| --- | --- |
| 公开源码快照 | 173 项选定 CPU 回归测试通过；前端生产构建与根项目 TypeScript 检查通过 |
| 打包 | 公共协议、teleop 和 backend 的 wheel 构建通过；已核对许可证文件与预编译厂商控制台的排除情况 |
| 此前的仿真端到端验证 | 内部前序版本完成 100 帧、4 路相机采集，经过 QA 门控导出 LeRobot 并通过 CPU 读取 |

此前采集由 agent 发送 Keyboard 消息完成，保留的是一条**抓取任务失败的轨迹**；
其证据支持数据链路，不代表任务成功。当前公开快照尚未重新运行 GPU 采集，也未完成
物理 GELLO、真机、全新机器复现或下游训练验证。173 项为选定测试集合，并非完整测试套件。
详细结果见[验证记录](docs/VALIDATION.md)。

### 运行环境与资产

可选 WebRTC 控制台提供[集成源码](teleop/web_console/)，不分发包含 NVIDIA 库的
预编译产物。请核对适用条款后[本地构建](docs/INSTALLATION.md#optional-collector-console)。
未构建时 Collector 根页面会提示 `Web console is not built`；worker 的 WebSocket
接入与录制代码可独立使用。

仿真 SDK、机器人 USD、数据集与模型权重需单独配置。公开相机配置为 nominal 示例，
不能代替实物标定。布料、生成、资产等扩展默认关闭，需要分别配置依赖并验证。

## IPPLab 工具系列

RoboData Studio 负责实验室工具链中的采集与数据集准备。**SceneKit**（场景描述）与
**DataAugment**（数据增强）是规划中的系列名称；GELLO Remote 与 Robot Data Contracts
目前随本仓库维护。职责和发布状态见[工具系列路线](docs/ECOSYSTEM.md)。

## 许可证与致谢

贡献者有权授权的自有代码采用 [Apache-2.0](LICENSE)。第三方署名和例外见
[NOTICE](NOTICE)、[第三方声明](THIRD_PARTY_NOTICES.md)及[资产授权边界](docs/LICENSES_AND_ASSETS.md)。
外部 SDK 与资产保留各自条款。

封面为 AI 生成的概念插画，不是产品截图或实机结果；技术图依据现有接口绘制。
仓库包含[图片来源说明与可编辑技术图规格](docs/assets/README.md)。
