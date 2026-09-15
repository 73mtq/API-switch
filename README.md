# API Switch

给 **CC Switch** 批量导入模型的桌面小工具：填一个中转端点 → 拉取 `/v1/models` → 勾选想要的模型 → 直接写进 CC Switch。

- 只发 `GET /v1/models`，**不产生任何推理费用**
- 支持 **Claude / Codex / OpenCode** 三种供应商卡的写入方式
- 写入前自动备份，出问题可一键回滚
- 图形界面 + 命令行两种用法，零第三方依赖（只用 tkinter / urllib / sqlite3）

![主窗口](docs/screenshot.png)

---

## 目录

- [使用前准备](#使用前准备)
- [运行方式](#运行方式)
- [图形界面详解](#图形界面详解)
  - [1 连接](#1-连接)
  - [2 模型](#2-模型)
  - [3 写入目标](#3-写入目标)
  - [4 日志](#4-日志)
- [三种应用 × 两种模式怎么选](#三种应用--两种模式怎么选)
- [上下文长度（context / 最大输出）](#上下文长度context--最大输出)
- [备份与回滚](#备份与回滚)
- [命令行用法](#命令行用法)
- [打包成 exe](#打包成-exe)
- [常见问题](#常见问题)
- [文件说明](#文件说明)

---

## 使用前准备

1. 安装并**至少启动过一次 CC Switch**，让它生成配置文件：
   - 数据库：`~/.cc-switch/cc-switch.db`
   - 备份目录：`~/.cc-switch/backups/`
   - Codex 模型目录：`~/.codex/cc-switch-model-catalog.json`
2. **写入前必须完全退出 CC Switch**（包括托盘图标）。程序每 8 秒检测一次进程，运行时标题栏会红字提示「CC Switch 正在运行」，同时「写入」按钮自动禁用；运行时强行写入会直接报错中止。
3. Python 3.10+（Windows）。不需要 `pip install` 任何东西。

## 运行方式

```bash
# 图形界面
python app.py

# 命令行（不需要界面，见下文）
python ccs_models.py --help
```

也可以直接用打包好的 `dist/API-Switch.exe`（见[打包成 exe](#打包成-exe)）。

---

## 图形界面详解

界面从上到下是四张卡片：连接 → 模型 → 写入目标 → 日志。窗口不够高时整页可滚动。

### 1 连接

| 字段 | 说明 |
| --- | --- |
| 端点 | 中转的 base URL，例如 `https://api.example.com/v1`。程序会自动尝试 `/v1/models` |
| API Key | 点「显示 / 隐藏」切换明文；日志里的 Key 会自动打码 |
| 鉴权 | `Bearer`（OpenAI 兼容）/ `x-api-key`（Anthropic）/ `x-goog-api-key`（Google） |
| UA | 自定义 User-Agent。部分网关按 UA 过滤，留空则用默认 |
| models 地址 | 手工指定模型列表地址，填了就只用它，不再自动推导 |
| 完整 URL 模式 | 端点填的是完整对话地址（如 `https://x.com/v1/chat/completions`）时勾选，会自动推回 `/v1/models` |

点「拉取模型列表」后，按钮变「拉取中…」并显示进度条，结果填入下方列表，同时保存到 `out/models.json` 和 `out/models.txt`。

端点的自动兜底规则：带 `/api/claudecode`、`/api/anthropic`、`/apps/anthropic` 等兼容后缀时，会同时尝试去掉后缀后的 `/v1/models`；带 `/v1`、`/v3` 这类版本号时补 `/models`。失败时日志会打印每个候选地址的原因，可以直接把能用的地址填进「models 地址」。

### 2 模型

- **搜索**：按模型 ID 或名称过滤（框里是灰色占位提示，点进去才清空）。
- **批量选择**：全选 / 全不选 / 反选 / 仅 Claude·Anthropic（只勾 ID 里带 `claude` 或 `anthropic` 的）。
- **单个勾选**：点一行任意位置即可，也可以选中后按空格；双击同样切换。勾选行会显示淡蓝底和 `✓`。
- **上下文列**：接口在 `/v1/models` 里返回了上下文长度才显示（如 `200K`、`1M`），没返回就是空白。
- 右侧计数会显示「已选 N · 共 M 个模型 · 接口给出 K 个上下文」。

### 3 写入目标

**模式**

- **一张卡 + 模型列表**：把所有模型塞进同一张卡（Claude 写 modelPicker，OpenCode 写 models 列表，Codex 写模型目录）。日常最常用。
- **每个模型一张卡**：以某张卡为模板，每个模型复制出一张新卡（端点、Key、环境沿用模板，只换模型名）。适合要在 CC Switch 里逐个对比/切换的场景。

**应用**：`claude` / `codex` / `opencode`，选完会自动刷新下面的「供应商卡」下拉。

**供应商卡**：写入的目标卡（fanout 模式下是模板卡）。下拉里是 `名称（id）`。下拉空说明该应用下还没有卡，可点「新建卡…」建一张。

**卡名前缀**：仅 fanout 模式生效，新卡名字是 `前缀 + 模型ID`。

**选项**

| 选项 | 生效范围 | 作用 |
| --- | --- | --- |
| 只显示我选的模型 | Claude + 一张卡模式 | 覆盖内置模型列表，只留你勾选的 |
| 同时开启网关模型发现 | Claude + 一张卡模式 | 顺手写 `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` |
| 合并到已有模型列表 | OpenCode + 一张卡模式 | 保留卡里原有模型，不覆盖 |
| 上下文 / 最大输出 | OpenCode（两者）、Codex（仅上下文） | 见[下文](#上下文长度context--最大输出) |
| 同时填 Sonnet / Opus / Haiku 槽位 | 每个模型一张卡模式 | 一并写 `ANTHROPIC_DEFAULT_*_MODEL` |

**按钮**：预览变更（只读，先看再写）→ 写入（自动备份）→ 回滚上一次写入；右侧是新建卡…/ 删除卡…（删除默认拒绝删正在使用的卡，可勾选强制删除）。

### 4 日志

显示请求过程、命中的地址、写入结果、备份路径。右上角「清空」。出错时日志打红字并弹窗。

---

## 三种应用 × 两种模式怎么选

| 应用 | 一张卡 + 模型列表 | 每个模型一张卡 |
| --- | --- | --- |
| **claude** | 写目标卡的 `modelPicker`（在 CC Switch 里以下拉形式选模型） | 每张卡一个模型，可填 Sonnet/Opus/Haiku 槽位 |
| **codex** | 写 `~/.codex/cc-switch-model-catalog.json` 模型目录，并给卡挂 `model_catalog_json` | 每张卡一份 TOML 配置，`model` 各不相同 |
| **opencode** | 写目标卡 `settings_config` 里的 `models` 列表（含 context/output limit） | 不支持（OpenCode 卡自带模型列表，请用一张卡模式） |

---

## 上下文长度（context / 最大输出）

- **能不能自动拿到**：看中转。官方 OpenAI / Anthropic / Google 的 `/v1/models` **不返回**上下文长度；但很多中转网关会带 `context_window`、`max_context_tokens`、`limits.context`、`maxTokens` 等字段。程序会尽力识别这些字段（含嵌套的 `limits` / `capabilities`，支持 `1,000,000`、`200K`、`1M` 这类写法），识别到就显示在列表的「上下文」列。
- **优先级**：接口给了某个模型的值 → 用它的；没给 → 用「上下文 / 最大输出」输入框里的兜底值（默认 1M / 128K）。
- **拉到最大**：拉取完成后，程序会自动把输入框填成接口返回过的**最大上下文**；也可以随时点「取接口最大值」重取，或手填（支持 `256000`、`256K`、`1M`）。
- **适用范围**：只有 **OpenCode**（`limit.context` / `limit.output`）和 **Codex**（`context_window` / `max_context_window`）有地方写；**Claude 卡没有这个字段**，所以选 claude 时这两项是禁用的。
- 预览里会写清楚「上下文 X（其中 N 个模型用接口返回值）」还是「接口未返回，使用手动值」。

---

## 备份与回滚

- 每次写入（含新建卡、删除卡）前都会自动备份到 `~/.cc-switch/backups/`，Codex 目录也会单独备份。
- 写入后右下角显示最近一次备份路径，「回滚上一次写入」按钮变可用，点一下把数据库还原回去。
- 命令行也可以直接还原：`python -c "import ccs_models as c; print(c.rollback(r'路径'))"`。

---

## 命令行用法

不需要界面时（服务器、批量脚本）用 `ccs_models.py`：

```bash
# 1) 拉模型 → 保存到 out/models.json 与 out/models.txt，并打印编号清单
python ccs_models.py fetch --base-url https://api.example.com/v1 --key sk-xxx

# 2) 再看一次编号
python ccs_models.py show

# 3) 写入（--provider 是目标卡 id；--pick 支持 1,3,5-9；--dry-run 只看不写）
python ccs_models.py apply --mode claude --provider <provider-id> --pick 1,3,5-9 --dry-run
```

常用参数：

| 参数 | 说明 |
| --- | --- |
| `--api-format` | `openai` / `anthropic` / `google` |
| `--models-url` | 手工指定模型列表地址 |
| `--ua` | 自定义 User-Agent |
| `--full-url` | 端点填的是完整 URL |
| `--mode` | `claude` / `codex` / `opencode` / `fanout` |
| `--app` | fanout 模式下的应用类型 |
| `--append` | 保留内置模型行（不覆盖） |
| `--merge` | OpenCode：合并到已有模型列表 |
| `--discovery` | 同时开启网关模型发现 |
| `--pick-file` | 从文件读模型 ID 列表（`#` 开头为注释） |

管理卡片：

```bash
python ccs_models.py new-card --app claude --name "我的中转" --base-url https://api.example.com/v1 --key sk-xxx
python ccs_models.py del-card --app claude --ids id1,id2 [--force]
```

Key 不写在命令行时，可设环境变量 `CCS_API_KEY`，否则会交互式提示（不回显、不保存）。

---

## 打包成 exe

```bat
build.bat
```

即 `python -m PyInstaller --noconsole --onefile --clean --name "API-Switch" app.py`，产物在 `dist/API-Switch.exe`。需要 `pip install pyinstaller`。

---

## 常见问题

**提示「CC Switch 正在运行」** — 完全退出 CC Switch（含托盘）再写入，程序每 8 秒自动复查一次。

**拉取失败 / 0 个模型** — 看日志里逐个候选地址的原因。常见：端点缺 `/v1`、网关要求特定 UA、鉴权头不对（换「鉴权」下拉）、返回的是嵌套结构（可直接把可用地址填进「models 地址」）。

**供应商卡下拉是空的** — 该应用下还没有卡，先在 CC Switch 里建一张，或点「新建卡…」。

**写入后 CC Switch 里看不到** — 确认已重启 CC Switch；Claude 卡用的是 modelPicker 列表，需要勾了「只显示我选的模型」才完全覆盖；fanout 模式建的是新卡，在列表里往下找。

**上下文没有值** — 中转的 `/v1/models` 没返回上下文字段，属正常。手动填「上下文」即可（只对 OpenCode / Codex 生效）。

**会不会偷偷调用模型** — 不会。全程只有 `GET /v1/models`。

---

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `app.py` | 图形界面（tkinter，零第三方依赖），也是所有 UI 逻辑 |
| `ccs_models.py` | 核心逻辑：请求模型列表、读写 CC Switch 数据库/Codex 目录、备份回滚、命令行 |
| `build.bat` | PyInstaller 打包脚本 |
| `API-Switch.spec` | PyInstaller 配置 |
| `out/` | 最近一次拉取的模型清单（`models.json` / `models.txt`），运行时生成 |
| `dist/` | 打包产物，运行时生成 |

写完就跑：填端点 → 拉取 → 勾选 → 预览 → 写入。
