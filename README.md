# Commerce Monitor

面向电商运营的商品与竞品监控 Agent 原型。支持商品登记、竞品发现与关联、变更分析、运营建议审核、执行任务和反馈闭环。界面为中文。

本仓库不含个人账号、数据库、API 密钥、购物平台登录状态或真实采集数据。默认使用本地录入和合成示例数据，不自带淘宝在线数据权限。

## 功能

- 自有商品与竞品管理、授权商品库导入、匹配与关联。
- 持久化监控计划、任务队列、快照与变更分析。
- 文本/截图辅助提取；可配置多模态模型及受控浏览器适配器。
- 建议审核、运营与美工任务、反馈、知识检索和报告。
- 租户隔离、角色权限、访问频率控制、去重、异常暂停及审计。

## 本地启动

要求 Python 3.12；首次安装需要联网。推荐使用独立虚拟环境。

```sh
git clone https://github.com/Alesia0411/commerce-monitor.git
cd commerce-monitor
python scripts/setup.py
python run.py
```

打开 http://127.0.0.1:8000。首次运行生成 `.local-credentials.json`，用其中对应租户的管理员账号登录。此文件和运行数据库仅保存在本地，不要提交到仓库。

安装脚本将 Python 依赖放在 `.deps/`，并下载固定版本 Vue 至 `web/vendor/`。两者均不纳入版本控制。离线规则分析无需模型密钥；可选模型通过进程环境变量 `MODEL_NAME`、`MODEL_API_KEY` 和 `MODEL_BASE_URL` 配置。Python 启动器不会自动加载 `.env`。

## MySQL 与 Redis

复制 `.env.example` 为 `.env`，替换两个数据库密码，再运行：

```sh
docker compose up --build
```

Compose 自动读取 `.env`。密码请使用随机字母和数字，避免数据库 URL 特殊字符。容器数据库持久化在 Docker volume 中。容器化部署仍需在你的环境验证；请勿直接作为公网生产服务部署。

## 验证

```sh
python test.py
node --check web/app.js
node --check web/workspace.js
node --check web/capture.js
node scripts/check-template.cjs
```

模板检查需要先通过安装脚本下载 Vue。可选浏览器安装及两种采集模式见 [采集说明](docs/CAPTURE.md)。浏览器功能需要额外依赖与站点配置；遇到登录、验证码或访问限制时暂停，由使用者处理。不包含验证码绕过或隐蔽采集机制。

## 目录与文档

| 目录 | 职责 |
|---|---|
| `app/` | FastAPI、领域服务、LangGraph 工作流、存储与适配器 |
| `web/` | Vue 运营界面 |
| `tests/` | 权限、业务、竞品发现、采集及风控测试 |
| `scripts/` | 安装、评测与模板检查 |
| `docs/` | 架构、使用说明与论文技术来源 |

- [技术架构](docs/TECHNICAL.md)
- [原型使用说明](docs/PROTOTYPE.md)
- [采集模式](docs/CAPTURE.md)
- [论文与实现范围](docs/PAPERS.md)
- [贡献指南](CONTRIBUTING.md) · [安全说明](SECURITY.md)

这是本地可运行的项目原型。生产级分布式调度、真实平台接入、完整论文复现等能力以技术文档列明的边界为准。

## 许可证

本项目原创代码采用 [MIT](LICENSE) 协议。第三方依赖分别遵循各自许可证，见 [第三方说明](THIRD_PARTY_NOTICES.md)。使用者应确认输入数据的授权范围并遵守目标平台规则。
