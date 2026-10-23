# Edge 职位本地数据库

数据库位于 `data/linkedin/positions.sqlite3`，与服务端数据库独立，作为本地采集暂存库。使用 Python 标准库，无需安装依赖。

在项目根目录运行：

```powershell
python -m clients.linkedin_database import "C:\Users\展红\Downloads\linkedin-usa-实际文件名.json"
python -m clients.linkedin_database stats
python -m clients.linkedin_database query --country US --keyword Data
python -m clients.linkedin_database query --country AU --keyword Nurse
```

`positions` 按领英职位 ID 跨批次去重，保留首次/最近采集时间、国家/州、职业组、SOC/ANZSCO 字段；空详情不会覆盖已有详情。`batches` 保留原始文件与内容哈希，重复文件跳过。`observations` 保留每批职位原始记录，`coverage_queries` 保留查询分区状态、结果数量、失败原因和完成时间。`lifecycle_status=possibly_closed` 与 `possibly_closed_at` 只接受导出记录明确提供的标记，不会因为一次查询缺席就误判职位下架。错误批次整体回滚。

search_country 表示搜索目标国家，不代表已核实的实际办公国家。Edge 下载 JSON 后可以手动执行导入，也可以运行本地监听器自动导入（不会控制浏览器或改变领英请求）：

```powershell
.\.venv\Scripts\python.exe scripts\watch_linkedin_downloads.py
```

监听器只处理下载目录中稳定的 `linkedin-*.json` 文件；重复文件按 SHA-256 跳过。遇到格式错误会记录日志并继续运行。

## 写入网站

项目自带网站名称为「职位聚合平台」：

- 网站：`http://localhost:3000`
- API：`http://localhost:8010`

监听器可以在导入本地 SQLite 的同时，把扩展导出的职位上传到网站的私有职位工作区。先按项目 README 的说明创建一个本地采集设备并保存一次性设备令牌，然后设置环境变量：

```powershell
$env:JOBAGG_DEVICE_TOKEN = "jagg_..."
$env:JOBAGG_API_BASE_URL = "http://localhost:8010"
.\.venv\Scripts\python.exe scripts\watch_linkedin_downloads.py
```

上传接口使用批量去重，重复下载不会重复写入。LinkedIn 职位会标记为当前设备的私有数据，不会自动公开到其他用户的搜索结果；可通过网站对应的私有导入工作区/API 查看。
