# SEEK Australia Registered Nurse 采集封装文档

## 1. 文档目的

本文说明项目内 SEEK Australia Registered Nurse 采集组件的封装边界、安装配置、数据结构、运行流程、限额、去重、异常处理和验收方式。

当前实现是“本地 Edge 扩展 + 私有导入 API + PostgreSQL + 管理后台”的人工辅助采集方案。扩展只处理用户已经打开并加载完成的公开 SEEK 页面，不负责自动登录、自动翻页、代理轮换、CAPTCHA 处理或绕过 Cloudflare/429。无人值守采集应使用已获授权的 SEEK API，或 Adzuna 等允许程序化访问的数据源。

## 2. 组件清单

| 组件 | 位置 | 作用 |
| --- | --- | --- |
| Edge 扩展 | `clients/seek_edge_extension/` | 读取当前 SEEK 页面、在本地预校验并上传 |
| 解析和字段标准化 | `clients/seek_edge_extension/core.js` | 解析职位 ID、标题、地点、薪资、发布时间、详情及护士标签 |
| 页面内容脚本 | `clients/seek_edge_extension/content.js` | 检测详情页、阻断页及当前页面可用数据 |
| 扩展后台 | `clients/seek_edge_extension/background.js` | 保存配置、调用导入 API、维护本地已见职位 |
| 导入网关 | `apps/api/import_gateway.py` | 认证、服务端校验、配额、幂等、入库和来源追踪 |
| 导入接口 | `apps/api/routers/import_jobs.py` | 设备管理、上传、查询进度及后台统计 |
| SEEK 规则 | `packages/seek_policy.py` | 7天窗口、标题范围、75分完整度、护士标签和配额 |
| 管理后台 | `apps/web/app/admin/imports/page.tsx` | 展示采集数据库、批次、进度和异常 |

## 3. 数据流

```text
用户在 Edge 打开 SEEK 搜索结果
  -> 用户点开一个职位并等待完整详情显示
  -> 点击扩展“采集当前页并上传”
  -> 扩展检查 CAPTCHA/429/登录页/页面结构
  -> 解析并执行本地 Registered Nurse 规则
  -> Bearer 设备令牌调用 POST /api/v1/import/jobs
  -> 服务端再次验证来源、日期、字段和配额
  -> PostgreSQL 去重并插入或更新
  -> 写入导入批次和来源追踪
  -> 管理后台立即显示结果
```

扩展端校验用于快速反馈；服务端校验是最终准入标准。客户端校验不能替代服务端规则。

## 4. 采集范围

### 4.1 基本条件

- 来源域名必须是 `seek.com.au`、`www.seek.com.au` 或 `au.seek.com`。
- 国家必须是澳大利亚，标准代码为 `AU`。
- 发布时间必须在最近7天内。
- 必须存在公司或招聘机构、地点、完整描述及规范职位链接。
- 职位不能显示已关闭。
- 完整度必须达到75分。

### 4.2 标题规则

优先标题：

- Registered Nurse
- RN
- Clinical Nurse

允许的扩展方向：

- Practice Nurse
- Community Nurse
- Aged Care Registered Nurse
- Mental Health Nurse
- Theatre Nurse
- Emergency Nurse
- ICU Nurse
- Paediatric Nurse
- Oncology Nurse
- Scrub Scout Nurse
- Perioperative Nurse

排除纯以下职位：

- Enrolled Nurse
- Assistant in Nursing / AIN
- Personal Care Worker
- Nurse Assistant
- Nursing Student

同时出现 Registered Nurse 和 Enrolled Nurse 的职位允许入库，并标记 `mixed_nurse_title=true`。

### 4.3 完整度评分

| 字段 | 分值 |
| --- | ---: |
| 职位名称 | 10 |
| 公司名称 | 10 |
| 城市或州 | 10 |
| 发布时间 | 15 |
| 完整描述 | 25 |
| SEEK 规范链接 | 10 |
| 工作类型 | 5 |
| 薪资 | 5 |
| 专业方向 | 5 |
| 排班信息 | 5 |

搜索结果卡片通常只有摘要，无法满足完整描述要求。应先打开职位，使右侧或独立详情页完整加载，再执行采集。

## 5. 安装与配置

### 5.1 服务端环境

复制 `.env.example` 为 `.env`，至少设置：

```dotenv
DATABASE_URL=postgresql+psycopg://jobuser:jobpass@localhost:5432/jobs
API_KEY=<管理员密钥>
ENABLE_IMPORT_GATEWAY=true
ENABLE_SEEK=false
```

`ENABLE_SEEK=false` 必须保持关闭，除非已取得允许服务器端程序化访问的正式授权。Edge 本地导入使用 `seek_user_import`，不依赖该开关。

默认本地地址：

- Web 管理后台：`http://localhost:3000/admin/imports`
- API：`http://localhost:8010`

### 5.2 创建设备令牌

设备创建接口要求管理员 `X-API-Key`：

```powershell
$headers = @{ 'X-API-Key' = '<API_KEY>' }
$body = @{
  name = 'My SEEK Edge'
  owner = '<用户标识>'
  platform = 'seek'
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri 'http://localhost:8010/api/v1/import/devices' `
  -Headers $headers `
  -ContentType 'application/json' `
  -Body $body
```

响应中的设备令牌只显示一次。扩展中只能填写设备令牌，不能填写管理员 `API_KEY`。

### 5.3 加载 Edge 扩展

1. 打开 `edge://extensions`。
2. 开启“开发人员模式”。
3. 点击“加载解压缩的扩展”。
4. 选择 `clients/seek_edge_extension`。
5. 打开扩展弹窗。
6. API 地址填写 `http://localhost:8010`。
7. 填入设备令牌并保存。
8. 修改扩展代码后，在扩展管理页点击“重新加载”，再刷新 SEEK 页面。

扩展版本记录在 `clients/seek_edge_extension/manifest.json`。当前封装版本为 `1.0.2`。

## 6. 标准操作流程

1. 在 Edge 打开：

   `https://au.seek.com/Registered-Nurse-jobs?daterange=7&sortmode=ListedDate`

2. 如果出现安全验证，由用户自行完成。扩展不得尝试绕过。
3. 在搜索结果中点开一个职位。
4. 等待标题、公司、地点、发布时间和完整描述加载完成。
5. 点击扩展图标。
6. 点击“采集当前页并上传”。
7. 查看新增、重复、本地跳过和服务端拒绝数量。
8. 返回搜索列表，按正常人工浏览节奏继续下一条。

推荐结果状态：

```text
完成：上传 1，新增 1，服务端重复 0，本地跳过 0
running · 今日有效 1/200 · 本小时 1/20
```

## 7. 配额与调度

服务端硬性限制：

- 每小时最多新增20条有效 SEEK 职位。
- 每天最多新增200条有效 SEEK 职位。
- 重复、更新和不合格数据不计入有效新增。
- 未使用的小时额度不累积。
- 达到小时上限后状态为 `waiting`。
- 达到日目标后状态为 `done`。

这些数字是上限和目标，不代表平台允许的访问频率。出现访问限制时，以暂停和冷却为优先，不能为了完成目标而集中访问。

## 8. API 封装

### 8.1 上传职位

```http
POST /api/v1/import/jobs
Authorization: Bearer <device-token>
Idempotency-Key: seek-<uuid>
Content-Type: application/json
```

请求示例：

```json
{
  "source": "seek_user_import",
  "query": "https://au.seek.com/Registered-Nurse-jobs?daterange=7",
  "jobs": [
    {
      "source": "seek_user_import",
      "source_job_id": "94795151",
      "title": "Registered Nurse - Day Surgery",
      "company": "Example Hospital",
      "description": "完整职位描述……",
      "country": "AU",
      "state": "QLD",
      "city": "Brisbane",
      "employment_type": "Part time",
      "canonical_url": "https://au.seek.com/job/94795151",
      "salary_min": 39.96,
      "salary_max": 54.01,
      "salary_currency": "AUD",
      "salary_period": "hour",
      "posted_at": "2026-09-23T00:00:00Z",
      "raw_payload": {
        "detail_status": "complete",
        "location_text": "Greenslopes, Brisbane QLD",
        "specialty_tags": ["Theatre"],
        "ahpra_required": true
      }
    }
  ]
}
```

典型响应字段：

- `accepted_count`：新增有效职位。
- `duplicate_count`：已存在或更新的职位。
- `rejected_count`：未通过规则的数据。
- `errors`：逐条拒绝原因。
- `progress`：今日、本小时和最近7天进度。

### 8.2 查看设备数据

```http
GET /api/v1/import/jobs?page=1&page_size=25
Authorization: Bearer <device-token>
```

### 8.3 管理员视图

```http
GET /api/v1/import/admin?page=1&page_size=50
X-API-Key: <API_KEY>
```

## 9. 去重与更新

浏览器端使用 `source_job_id` 保存最近已上传记录，减少重复请求。服务端再次执行持久化去重，最终以数据库结果为准。

建议的去重优先级：

1. SEEK 职位 ID。
2. 规范化职位链接。
3. 公司 + 标准化职位名称 + 城市。
4. 招聘机构 + 标准化职位名称 + 地区。
5. 职位描述指纹。

重复数据不新增职位，只更新适用字段并记录导入来源。每次上传均使用唯一 `Idempotency-Key`；同一批次重放时不会重复入库。

## 10. 状态与异常

| 状态 | 含义 |
| --- | --- |
| `running` | 可以继续采集 |
| `waiting` | 本小时20条额度已完成 |
| `paused` | 需要人工处理或页面无法识别 |
| `cooldown` | 发生访问频率限制，需要等待 |
| `done` | 今日200条完成 |

以下情况必须停止：

- CAPTCHA、Cloudflare 或其他安全验证。
- HTTP 429 或明确的访问频率限制。
- 登录失效。
- 页面结构无法识别。
- 搜索条件意外改变。
- 连续页面加载失败。

不得通过频繁刷新、代理轮换、指纹伪装、新建任务或更换会话绕过限制。

## 11. 常见问题

### 11.1 提示“本页没有符合规则的完整职位”

通常表示当前只是搜索摘要页，或职位详情仍在加载。点开一个职位并等待完整描述出现后重试。

### 11.2 提示“Could not establish connection”

扩展重新加载后，旧页面可能没有新的内容脚本。刷新 SEEK 页面后再点击扩展。后台也会在用户明确点击时尝试重新注入脚本一次。

### 11.3 提示“设备令牌无效”

检查：

- API 地址是否为 `http://localhost:8010`。
- 填写的是否为设备令牌，而非管理员 API Key。
- 设备是否被撤销。
- API 服务是否正在运行。

### 11.4 为什么一次通常只新增一条

有效标准要求完整职位描述。SEEK 搜索结果卡片只有摘要，当前打开的详情通常只有一条满足完整性要求，因此一次新增一条属于预期行为。

### 11.5 为什么不能一次采集搜索页全部结果

搜索页摘要不足以达到75分完整度，而且自动打开大量详情页容易触发安全验证。8,087等页面计数也可能包含超过7天、不合格或重复职位。

## 12. 测试与验收

运行扩展解析测试：

```powershell
node --test clients/seek_edge_extension/*.test.cjs
```

运行 SEEK 服务端规则测试：

```powershell
pytest tests/test_seek_policy.py tests/test_seek_import.py tests/test_import_gateway.py
```

验收检查：

- 最近7天之外的职位被拒绝。
- 纯 Enrolled Nurse 等职位被拒绝。
- Registered Nurse + Enrolled Nurse 混合职位被保留并标记。
- 不完整描述不计入有效职位。
- 同一职位重复上传不产生第二条记录。
- 每小时第21条新职位被拒绝。
- 每日第201条新职位被拒绝。
- 成功数据立即出现在管理员后台。
- CAPTCHA、429及安全验证不会被自动处理。

## 13. 可替换的数据源层

若需要无人值守运行，保留现有标准化、校验、去重、PostgreSQL和后台展示层，只替换采集适配器：

```text
获批 SEEK API / Adzuna API
  -> 标准化为 NormalizedJob
  -> packages/seek_policy.py 或同等护士规则
  -> persist_job_row_safe
  -> PostgreSQL
  -> 管理后台
```

项目已经提供 `collectors/adzuna_adapter/` 和 `AU_NURSE_PLAN_*` 配置。取得 Adzuna 凭据后，可开启 API 支持的自动计划；SEEK Edge 扩展继续作为人工补充来源。

## 14. 安全边界

- 不在服务端保存 SEEK 用户名、密码或浏览器 Cookie。
- 设备令牌仅保存在扩展 `storage.local`。
- 导入职位标记为 `private`、`user_local` 并绑定设备。
- 私有导入数据不进入未经授权的公开搜索和市场统计。
- 管理员密钥不得写入扩展。
- 不使用 Scrapling Stealth、代理轮换、Cloudflare 求解或类似反检测功能访问 SEEK。
- 在部署和运行前，由系统所有者确认数据使用方式符合 SEEK 条款及适用法律。

