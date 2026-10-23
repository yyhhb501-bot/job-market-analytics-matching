# Docker 每日领英职位采集

在本目录执行以下命令（需要 Docker Desktop 正在运行）。

```powershell
docker compose build
docker compose up -d browser
docker compose run --rm collector python runner.py login
```

第三条命令等待登录。打开 http://localhost:7900 ，在容器浏览器中手动登录领英；登录成功后命令退出并保存会话。此会话独立于 Windows Edge，不复制 Edge Cookie。

```powershell
# 首次立即采集
docker compose run --rm collector python runner.py once
# 启动每日更新
docker compose up -d collector
# 查看运行日志
docker compose logs -f collector
```

默认北京时间每天 08:00 执行；当天 08:00 后首次启动会补跑一次。电脑和 Docker 必须保持运行。config.json 配置美国全国 Data、澳洲全国 Nursing，办公方式不限，近 7 天，每关键词 5 页，每类每次最多新增 250 条。修改配置后重启 collector。

数据保存到项目 data/linkedin-daily：jobs.sqlite3 为逐条提交的去重数据库，us-data.json、au-nursing.json 为累积导出，runs.jsonl 记录成功/失败和错误。重复职位不重复抓详情；此版本增量发现新增职位，不核验旧职位下架或描述变更。分页、条数及平台可见性限制意味着结果不是全站全集。

运行状态记录在 data/linkedin-daily/collect-state.json：尝试时间/次数与成功时间分开记录，失败当天按 30 分钟起步的退避自动重试（每天最多 3 次），成功标记只在成功后写入；出现登录墙或安全验证时任务进入暂停状态，不再自动重试，人工执行 once/login 成功后自动恢复。已保存数据保留。重新登录步骤：

```powershell
docker compose stop collector
docker compose run --rm collector python runner.py login
docker compose run --rm collector python runner.py once
docker compose up -d collector
```

浏览器操作网页只绑定本机 127.0.0.1。不要把 7900 端口暴露到公网。浏览器资料保存在 Docker 命名卷中；不要执行 docker compose down -v，否则会删除登录会话。
