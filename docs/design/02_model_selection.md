# 02 · 前端模型选择（M2）

> 状态：`final`（已评审定稿）　|　上位文档：[00_overview.md](00_overview.md)（final）、[01_llm_factory.md](01_llm_factory.md)（final）
> 修订记录：2026-09-19 初稿；同日模型选择 UI 由原生 select 改为 WorkBuddy 风格上拉弹层
> 改动点基于 2026-09-19 对 `Composer.tsx` / `App.tsx`（props 结构）/ `agentApi.ts` / `query_router.py` / `query_schema.py` 的现状核对。

---

## 1. 目标与边界

### 1.1 做什么

1. **后端**：`GET /api/models` 返回可用模型（provider）列表（从 `app_config.llm.providers` 读取，前端不硬编码）；`POST /api/query` 请求体新增 `model` 字段
2. **前端**：`Composer` 输入框内增加模型选择下拉（按厂商分组展示 4 个 provider）；选定模型随每次请求传递；选择持久化到 `localStorage`
3. 数据流：`Composer(下拉) → App.tsx(state) → agentApi.streamQuery(model) → QuerySchema.model → QueryService.query(model) → create_llm`（最后两步已在 01 落地）

### 1.2 不做什么

- 不做模型能力说明页/价格展示 UI（下拉的 `title` 提示仅显示 model 名）
- 不做请求中途切换模型（切换只影响下一次发送；流式中的请求不受影响）
- 不做多模型并行对比 UI（评估走 03 的 CLI，不在聊天界面）
- 不改 SSE 事件协议（本模块不产生新事件类型）

### 1.3 依赖模块

- 上游：01（`create_llm(provider)` 已支持按名创建与非法回退；`QueryService.query` 已有 `model` 参数）
- 下游：无（03 评估 CLI 直接用 provider 名，不经本模块）

---

## 2. 配置 Schema

本模块**不新增配置**。`GET /api/models` 的数据完全来自 `app_config.llm`（providers + default），保证"配置加一个 provider → 下拉自动多一项"。

前端不读取 yaml；`VITE_API_BASE_URL` 环境变量沿用现状（`agentApi.ts` L7）。

---

## 3. 接口与数据结构

### 3.1 `GET /api/models` 响应结构

```json
{
  "default": "deepseek-flash-offpeak",
  "providers": [
    { "name": "deepseek-flash-offpeak", "model": "deepseek-flash", "group": "DeepSeek", "price_tier": "offpeak" },
    { "name": "deepseek-flash-peak",    "model": "deepseek-flash", "group": "DeepSeek", "price_tier": "peak" },
    { "name": "qwen",                   "model": "qwen3.8-flash",  "group": "Qwen",     "price_tier": null },
    { "name": "glm",                    "model": "glm-5.3-flash",  "group": "GLM",      "price_tier": null }
  ]
}
```

- `group` 由后端从 provider 名推导（**不进配置**）：`deepseek-* → DeepSeek`、`qwen* → Qwen`、`glm* → GLM`、其余 → `Other`。推导映射硬编码在端点实现中，新增 provider 组时改这一处
- `price_tier` 直通配置（可能为 null）
- **不返回价格字段**：价格属评估域（03），避免诱导用户按价选模型的 UI 语义；如后续要展示，另行评审
- 分组顺序：按 `group` 名排序（DeepSeek / GLM / Qwen 字母序），组内按配置文件声明顺序

### 3.2 `QuerySchema` 变更（`app/api/schemas/query_schema.py`）

```python
from typing import Optional
from pydantic import BaseModel, Field

class QuerySchema(BaseModel):
    query: str
    thread_id: str
    model: Optional[str] = Field(default=None, max_length=64)  # [NEW] provider 名；None/非法 → 后端兜底 default
```

**校验策略（宽松）**：

- 只约束类型与长度，**不做枚举校验**——避免前端与配置强耦合（配置加 provider 不需要前端同步发版）；非法值由 01 的 `create_llm` 回退 default 并打 warning
- `None`（旧前端不传）→ 走 default，天然向后兼容

### 3.3 前端类型（`frontend/src/types/agent.ts`）[MODIFY]

```typescript
export type ModelInfo = {
  name: string;        // provider 名，作为请求体 model 值与下拉 value
  model: string;       // 物理模型名，用于 title 提示
  group: string;       // 分组名（下拉 optgroup）
  price_tier: string | null;
};

export type ModelsResponse = {
  default: string;
  providers: ModelInfo[];
};
```

### 3.4 API 客户端（`frontend/src/lib/agentApi.ts`）[MODIFY]

```typescript
export async function fetchModels(signal?: AbortSignal): Promise<ModelsResponse>
// GET ${API_BASE_URL}/api/models；网络失败/非 200 时抛错（由调用方降级处理）

export type QueryOptions = {
  signal?: AbortSignal;
  model?: string;              // [NEW] 未定义时请求体不含 model 字段（兼容后端默认值）
  onEvent: (event: AgentEvent) => void;
};
// streamQuery 内部：body = JSON.stringify({query, thread_id, ...(model ? {model} : {})})
```

### 3.5 UI 组件（`frontend/src/components/Composer.tsx`）[MODIFY]

**位置与形态**：在现有输入条（`form > div.mx-auto.flex`）内部、textarea **左侧**放置一个模型选择按钮；点击后**向上弹出**选择面板（类 WorkBuddy 的模型选择 UI）：

```
收起态：                                  展开态：
┌────────────────────────────────────┐   ┌────────────────────────────────────┐
│ ✦ deepseek-flash ▴  问个问题... [▲] │   │ ┌───────────────────────────────┐  │
└────────────────────────────────────┘   │ │ ● DeepSeek                    │  │
        按钮 = 当前模型短名 + ▴ 图标       │ │   ✓ deepseek-flash（低谷）     │  │
                （点击向上展开面板）        │ │     deepseek-flash（高峰）     │  │
                                         │ │ ● GLM                         │  │
                                         │ │     glm-5.3-flash             │  │
                                         │ │ ● Qwen                        │  │
                                         │ │     qwen3.8-flash             │  │
                                         │ └───────────────────────────────┘  │
                                         │ ✦ deepseek-flash ▴  问...     [▲]  │
                                         └────────────────────────────────────┘
```

```typescript
type ComposerProps = {
  value: string;
  disabled: boolean;
  isStreaming: boolean;
  models: ModelInfo[];            // [NEW] 空数组 = 后端不可达，按钮隐藏
  defaultModel: string;           // [NEW] 后端 default；无模型数据时为 ""
  selectedModel: string;          // [NEW] 受控值
  onModelChange: (name: string) => void;   // [NEW]
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
};
```

交互细节（上拉弹层）：

1. **触发按钮**：左侧按钮显示当前模型短名（物理模型名 + `▴` 图标，`price_tier` 有值时附"高峰/低谷"徽标文案）；无第三方依赖，面板用绝对定位手写（`absolute bottom-full mb-2 left-0`，挂在输入条容器 `relative` 上）
2. **面板结构**：按 `group` 分组渲染（组名小标题 + 组内条目）；每条目两行——第一行显示名（`deepseek-flash（低谷）`），第二行小字显示物理模型名；当前选中条目带 `✓`（lucide `Check`）高亮
3. **打开/关闭**：点击按钮 toggle；点击面板外（document 级 `pointerdown` 监听 + ref contains 判断）、按 `Escape`、或选中条目后自动关闭
4. **禁用态**：`isStreaming` 时按钮 `disabled`（面板不可展开；已展开时发送请求则先收起）
5. **空列表降级**：`models.length === 0` 时按钮不渲染（后端不可达/旧后端），请求不带 model
6. **定位与层级**：面板 `z-20` 以上避免被消息流遮挡；最大高度 `max-h-72 overflow-y-auto`（provider 多时可滚动）；紧贴输入条上沿，不遮盖正在输入的文本
7. **键盘可达性**：按钮 `aria-haspopup="listbox"` + `aria-expanded`；面板条目 `role="option"`；v1 不实现方向键导航（登记为后续增强项，不在 §6 验收范围）

### 3.6 状态管理（`frontend/src/App.tsx`）[MODIFY]

```typescript
const [models, setModels] = useState<ModelInfo[]>([]);
const [defaultModel, setDefaultModel] = useState("");
const [selectedModel, setSelectedModel] = useState<string>(
  () => localStorage.getItem("agent_model") ?? ""    // 初始从 localStorage 恢复
);

useEffect(() => {
  fetchModels()
    .then((res) => {
      setModels(res.providers);
      setDefaultModel(res.default);
      // localStorage 里的旧值若已不在列表中（配置变更），重置为 default
      const saved = localStorage.getItem("agent_model");
      if (!saved || !res.providers.some((p) => p.name === saved)) {
        setSelectedModel(res.default);
        localStorage.setItem("agent_model", res.default);
      }
    })
    .catch(() => { /* 拉取失败：models 保持 []，下拉隐藏，请求不带 model */ });
}, []);

const handleModelChange = (name: string) => {
  setSelectedModel(name);
  localStorage.setItem("agent_model", name);
};

// startQuery 内：streamQuery(input, { signal, model: selectedModel || undefined, onEvent })
```

- **持久化层级**：模型选择存 `localStorage`（跨会话保留用户偏好）；`thread_id` 仍存 `sessionStorage`（会话隔离，与本模块无关）——两者层级不同，**不得混用同一存储**
- **旧值失效处理**：localStorage 中的 provider 名不在当前 /api/models 列表时，重置为 default（应对配置删除了某 provider）
- `startQuery` 提交时把 `selectedModel` 传给 `streamQuery`；发送中的请求不受切换影响

---

## 4. 对现有代码的改动点清单

| # | 文件 | 位置 | 操作 | 内容 |
|---|------|------|------|------|
| 1 | `app/api/schemas/query_schema.py` | L11-16 | [MODIFY] | 新增 `model: Optional[str] = Field(default=None, max_length=64)`（§3.2） |
| 2 | `app/api/routers/query_router.py` | L28-43 | [MODIFY] | 新增 `@query_router.get("/api/models")` 端点（`models_handler`，读 `app_config.llm` 组装响应，含 group 推导）；`query_handler` L41 调用改为 `query_service.query(query.query, query.thread_id, model=query.model)` |
| 3 | `frontend/src/types/agent.ts` | 文件尾 | [MODIFY] | 新增 `ModelInfo` / `ModelsResponse` 类型（§3.3） |
| 4 | `frontend/src/lib/agentApi.ts` | L9-12（QueryOptions）、L29-40（streamQuery body） | [MODIFY] | `QueryOptions` 加 `model?: string`；body 按需携带；新增 `fetchModels()`（§3.4） |
| 5 | `frontend/src/components/Composer.tsx` | L9-16（props）、L45-48（图标区） | [MODIFY] | props 扩展 4 项；图标区改为模型选择按钮 + 上拉分组弹层（无第三方依赖，手写 popover，§3.5） |
| 6 | `frontend/src/App.tsx` | Composer 调用处 + 顶部 state | [MODIFY] | 新增 models/defaultModel/selectedModel state、mount 时 fetchModels、handleModelChange、startQuery 传 model（§3.6） |
| 7 | `app/api/dependencies.py` | — | **不变** | /api/models 无需依赖注入（直接读 app_config 单例） |
| 8 | `frontend/vite.config.ts` | — | 视现状 | 若 dev 代理未覆盖 GET 路由则补充；`VITE_API_BASE_URL` 直连时无此问题（编码时核实现有 proxy 配置） |

**明确不改**：SSE 事件结构、`thread_id` 逻辑（sessionStorage）、`EmptyState`/`MessageBubble` 等展示组件、后端 `QueryService`（01 已支持 model 参数）。

---

## 5. Feature Flags 开关语义

**本模块不受任何开关控制**：

- 模型选择是纯 UI + 配置透传能力，不改变 Agent 行为结构，没有"旧行为"可回退（旧行为 = 不传 model = default，这本身就是 `model=None` 的语义）
- 与 `usage_tracking` 的关系：选择不同 provider 产生的用量由 01 的 tracker 自动按 provider 归集，无需额外开关

---

## 6. 验收标准

1. **端点**：`GET /api/models` 返回 4 个 provider（分组正确：DeepSeek 组含 peak/offpeak 两项）、`default` 为 `deepseek-flash-offpeak`
2. **弹层渲染**：点击左侧按钮向上弹出分组面板（DeepSeek 组两条目带"高峰/低谷"后缀与选中 ✓ 标记）；配置文件删除某 provider 后重启，面板同步少一项（前端不硬编码验证）；点击面板外 / Escape / 选中后三种方式均可关闭
3. **选择生效**：切换到 `glm` 后发送问题，后端日志 `LLM usage | {...}` 中 `"provider": "glm"`；切回 offpeak 后日志 provider 对应变化
4. **持久化**：选择 glm → 刷新页面 → 按钮显示 glm 且面板中选中标记一致（localStorage）；手工篡改 localStorage 为不存在值 → 刷新后自动重置为 default
5. **兼容降级**：`localStorage` 清空首次访问 → 默认选中后端 default；后端停止时刷新页面 → 按钮隐藏、发送请求不带 model 字段、后端起来后功能恢复
6. **流式中禁用**：请求流式进行中按钮禁用（面板不可展开），结束后恢复
7. **旧客户端兼容**：不带 model 字段的请求（curl 直接构造）正常走 default
8. **类型同步**：`npm run lint`（tsc --noEmit）通过，无 any 逃逸
