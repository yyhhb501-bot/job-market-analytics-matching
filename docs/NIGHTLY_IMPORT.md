# 夜间职位入库

开发环境的 Celery Beat 每天北京时间 23:00 执行 `jobagg.nightly_local_import`。任务读取 `data/linkedin/positions.sqlite3` 和 `data/linkedin-daily/jobs.sqlite3`，通过现有导入网关把未处理的 LinkedIn 职位写入网站 PostgreSQL 的 `jobs` 表。它使用 `.env` 中的 `JOBAGG_DEVICE_TOKEN` 识别设备，因此记录在该设备名下，并可从 `/admin/imports` 查看导入批次。

SEEK 扩展在采集时已直接调用导入 API，职位当时就写入同一数据库，无需等到夜间。LinkedIn Edge 下载监听器如正在运行，也会实时上传；夜间任务负责补上本地 SQLite 中遗漏的记录。

补录进度保存在 `data/imports/nightly-sync-state.json`。每个批次提交后记录断点；再次执行只处理新记录。任务发生异常时每 30 分钟重试，最多 3 次。`worker`、`beat`、PostgreSQL 和本机 Docker 必须在计划时段运行。

检查任务：

```powershell
docker exec jobseek-worker-1 python -m apps.worker.nightly_import
docker logs --tail 50 jobseek-beat-1
```

手动检查命令会执行一次补录；已有记录不会再次新增。生产部署默认关闭此任务，需设置 `NIGHTLY_IMPORT_ENABLED=true`，并确保 worker、beat 能访问相同的本地 SQLite 文件及设备令牌。
