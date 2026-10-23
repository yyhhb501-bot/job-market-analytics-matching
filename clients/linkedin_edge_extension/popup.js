const status = document.querySelector('#status');
document.getElementById('versionText').textContent = chrome.runtime.getManifest().version;
const keys = ['plan','keywords','location','workplace','days','maxJobs','maxPages','delay','pageDwell','cooldownMinutes','maxRetries','maxQueries','splitThreshold','maxSplitDepth','includeRegions','excludes','strictTitle'];

const openDashboardBtn = document.getElementById('openDashboard');
if (openDashboardBtn) {
  openDashboardBtn.onclick = () => {
    chrome.tabs.create({ url: 'http://localhost:3000/admin/imports' });
  };
}

function applyPreset(name) {
  const p = globalThis.LINKEDIN_PRESETS?.[name];
  if (!p) return;
  for (const k of keys) {
    const el = document.getElementById(k);
    if (!el) continue;
    if (['strictTitle','includeRegions'].includes(k)) el.checked = !!p[k];
    else if (p[k] !== undefined) el.value = p[k];
  }
}

async function call(type, extra = {}) {
  const r = await chrome.runtime.sendMessage({ type, ...extra });
  if (!r?.ok) throw Error(r?.error || '操作失败');
  return r.value;
}

function config() {
  return Object.fromEntries(keys.map(k => [k, ['strictTitle','includeRegions'].includes(k) ? document.getElementById(k).checked : document.getElementById(k).value]));
}

function coverageText(run) {
  if (!run?.queue?.length) return '';
  const counts = run.queue.reduce((out, q) => (out[q.status || 'pending'] = (out[q.status || 'pending'] || 0) + 1, out), {});
  return `\n分区 ${Math.min((run.queueIndex || 0) + 1, run.queue.length)}/${run.queue.length} · 已完成 ${counts.done || 0} · 受限 ${counts.limited || 0} · 待处理 ${counts.pending || 0}`;
}

async function refresh() {
  try {
    const collector = await chrome.runtime.sendMessage({ type: 'collectorControl', platform: 'linkedin', action: 'status' });
    if (collector?.ok && collector.value) {
      const v = collector.value;
      const collectedEl = document.getElementById('metricCollected');
      const pendingEl = document.getElementById('metricPending');
      const syncedEl = document.getElementById('metricSynced');
      const titleEl = document.getElementById('statusSummaryTitle');
      const syncBadge = document.getElementById('syncBadge');

      if (collectedEl) collectedEl.textContent = v.collected != null ? String(v.collected) : '0';
      if (pendingEl) pendingEl.textContent = v.pendingSync != null ? String(v.pendingSync) : '0';
      if (syncedEl) syncedEl.textContent = v.synced != null ? String(v.synced) : '0';

      const labels = { running: '运行中', waiting: '等待中', retrying: '重试中', paused: '已暂停', done: '已完成', idle: '空闲' };
      if (titleEl) titleEl.textContent = `采集状态：${labels[v.status] || v.status}`;

      if (syncBadge) {
        if (v.syncError) {
          syncBadge.textContent = '入库异常';
          syncBadge.style.color = '#c62828';
        } else if (v.needsSetup) {
          syncBadge.textContent = '待连接控制台';
          syncBadge.style.color = '#e65100';
        } else {
          syncBadge.textContent = '直接入库就绪';
          syncBadge.style.color = '#2e7d32';
        }
      }
    }
  } catch {
    // collectorControl is optional fallback
  }

  const run = await call('state');
  const s = await call('scheduleState');
  const paced = await call('pacedState');

  if (s.schedule) {
    const dailyEnabledEl = document.getElementById('dailyEnabled');
    const dailyTimeEl = document.getElementById('dailyTime');
    if (dailyEnabledEl) dailyEnabledEl.checked = s.schedule.enabled;
    if (dailyTimeEl) dailyTimeEl.value = `${String(s.schedule.hour).padStart(2, '0')}:${String(s.schedule.minute).padStart(2, '0')}`;
  }

  const schedule = paced.enabled
    ? '每日目标 600 条 · 09:00–23:00（北京时间）已开启 · 美国＋澳洲合计每小时最多 50 次详情'
    : s.schedule?.enabled
    ? `每日 ${document.getElementById('dailyTime')?.value} 已开启`
    : '定时任务未开启';

  status.textContent = (run
    ? `${run.status} · ${Object.keys(run.jobs || {}).length} 条（详情完整 ${Object.values(run.jobs || {}).filter(j => j.detail_status === 'complete').length}）${coverageText(run)}\n页 ${(run.page || 0) + 1}\n${run.message || ''}`
    : '尚未开始') + `\n${schedule}`;

  if (run?.mode === 'paced') {
    status.textContent += `\n今日有效 ${paced.count}/${run.pacing?.target || 600} 条 · 不合格或重复 ${run.rejected || 0} 条\n${run.status === 'waiting' && run.pacing?.notBefore ? '下次检查：' + new Date(run.pacing.notBefore).toLocaleString() : ''}`;
  }

  if (run?.syncError) {
    status.textContent += `\n自动导出失败，稍后重试：${run.syncError}`;
  } else if (run?.syncPending) {
    status.textContent += '\n新增或更新数据等待自动导出（约 2 分钟）';
  } else if (run?.lastSyncExportAt) {
    status.textContent += `\n最近自动导出：${new Date(run.lastSyncExportAt).toLocaleString()}，由本地服务接收入库`;
  }

  const { lifecycleReview } = await chrome.storage.local.get('lifecycleReview');
  const reviews = Object.values(lifecycleReview?.reviews || {});
  status.textContent += `\n原链接复查 ${reviews.length} 条 · 已关闭 ${reviews.filter(x => x.status === 'closed').length} · 待复查 ${reviews.filter(x => x.status === 'unknown').length}${lifecycleReview?.pending ? ' · 有状态待同步' : ''}`;
}

document.getElementById('startPaced').onclick = async () => {
  try {
    await call('startPaced');
    await refresh();
  } catch (e) {
    status.textContent = e.message;
  }
};

for (const type of ['start', 'resume', 'stop', 'export']) {
  const el = document.getElementById(type);
  if (!el) continue;
  el.onclick = async () => {
    try {
      const c = config();
      if (type === 'start') await chrome.storage.local.set({ lastConfig: c });
      await call(type === 'start' && c.plan === 'all-occupations' ? 'startPaced' : type, type === 'start' ? { config: c } : {});
      await refresh();
    } catch (e) {
      status.textContent = e.message;
    }
  };
}

document.getElementById('applyPreset').onclick = () => applyPreset(document.getElementById('preset').value);
document.getElementById('preset').onchange = e => {
  if (e.target.value !== 'custom') applyPreset(e.target.value);
};

document.getElementById('saveSchedule').onclick = async () => {
  try {
    const [hour, minute] = document.getElementById('dailyTime').value.split(':').map(Number);
    await call('setSchedule', { schedule: { enabled: document.getElementById('dailyEnabled').checked, hour, minute } });
    await refresh();
  } catch (e) {
    status.textContent = e.message;
  }
};

document.getElementById('runDailyNow').onclick = async () => {
  try {
    await call('runDailyNow', { coverage: true });
    await refresh();
  } catch (e) {
    status.textContent = e.message;
  }
};

chrome.storage.local.get('lastConfig').then(({ lastConfig }) => {
  const safeCoverage = lastConfig?.plan === 'all-occupations' && Number(lastConfig.maxJobs) <= 300 && Number(lastConfig.delay) >= 12 && Number(lastConfig.cooldownMinutes) >= 360;
  if (safeCoverage) {
    document.getElementById('preset').value = 'custom';
    for (const k of keys) {
      const el = document.getElementById(k);
      if (!el) continue;
      if (['strictTitle', 'includeRegions'].includes(k)) el.checked = !!lastConfig[k];
      else if (lastConfig[k] !== undefined) el.value = lastConfig[k];
    }
  } else {
    applyPreset('all-occupations-backfill');
  }
});

refresh().catch(e => {
  status.textContent = e.message;
});

chrome.storage.onChanged.addListener(changes => {
  if (changes.run || changes.collectorConnection || changes.linkedinOutbox) {
    refresh().catch(() => {});
  }
});
