const status = document.querySelector('#status');
const continuousStatus = document.querySelector('#continuousStatus');
const autoButton = document.querySelector('#auto');
const pauseButton = document.querySelector('#pauseContinuous');
let currentRun = null;

const openDashboardBtn = document.getElementById('openDashboard');
if (openDashboardBtn) {
  openDashboardBtn.onclick = () => {
    chrome.tabs.create({ url: 'http://localhost:3000/admin/imports' });
  };
}

try {
  document.querySelector('#version').textContent = `v${chrome.runtime.getManifest().version}`;
} catch {
  document.querySelector('#version').textContent = '版本未知';
}

async function call(type, extra = {}) {
  const response = await chrome.runtime.sendMessage({ type, ...extra });
  if (!response?.ok) throw Error(response?.error || '扩展后台没有响应。');
  return response.value;
}

async function restore() {
  const data = await chrome.storage.local.get(['apiUrl', 'deviceToken', 'lastResult']);
  const apiUrl = data.apiUrl === 'http://localhost:8000' ? 'http://localhost:8010' : data.apiUrl;
  document.querySelector('#apiUrl').value = apiUrl || 'http://localhost:8010';
  if (apiUrl !== data.apiUrl) await chrome.storage.local.set({ apiUrl });
  document.querySelector('#deviceToken').value = '';
  document.querySelector('#deviceToken').placeholder = data.deviceToken ? '已保存；留空保留原连接' : '首次连接可直接使用采集控制台';
  if (data.lastResult) status.textContent = formatResult(data.lastResult);
}

function formatResult(value) {
  return `上次上传回执（历史结果）：接收 ${value.received_count || 0}，新增 ${value.accepted_count || 0}，重复 ${value.duplicate_count || 0}，拒绝 ${value.rejected_count || 0}，本地跳过 ${value.rejected_local || 0}。今日进度以上方实时核对为准。`;
}
function progressText(result) {
  if(!result?.value) return `服务端今日进度：未知。${result?.error || '正在核对。'}`;
  const p=result.value;
  const checked=new Date(result.checkedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
  return result.fresh
    ? `服务端今日有效 ${p.today_valid}/${p.today_target} · 本小时有效入库 ${p.hour_valid}/${p.hour_limit}（北京时间；核对 ${checked}）`
    : `最近一次核对 ${p.today_valid}/${p.today_target}（${checked} 北京时间，已过期，非今日实时进度）。${result.error || ''}`;
}

document.querySelector('#save').onclick = async () => {
  try {
    const token = document.querySelector('#deviceToken').value || (await chrome.storage.local.get('deviceToken')).deviceToken;
    await call('saveSettings', { apiUrl: document.querySelector('#apiUrl').value, deviceToken: token });
    document.querySelector('#deviceToken').value = '';
    status.textContent = '设置已保存在扩展本地存储中。';
    refreshRun();
  } catch (error) {
    status.textContent = error.message;
  }
};

async function collect(type) {
  try {
    status.textContent = type === 'collectVisibleAndUpload' ? '正在逐条打开并提取本页职位…' : '正在读取并上传当前页…';
    const value = await call(type);
    status.textContent = value.message || `完成：上传 ${value.uploaded || 0}，新增 ${value.accepted_count || 0}，服务端重复 ${value.duplicate_count || 0}，本地跳过 ${value.skipped || 0}`;
    if (value.attempted != null) status.textContent += `\n尝试 ${value.attempted} 条，详情失败 ${value.failures?.length || 0} 条`;
    if (value.failures?.length) status.textContent += `\n${value.failures.slice(0, 3).join('\n')}`;
    if (value.progress) status.textContent += '\n本次上传已返回回执；今日进度请以上方服务端实时核对为准。';
    refreshRun();
  } catch (error) {
    status.textContent = error.message;
  }
}

document.querySelector('#collect').onclick = () => collect('collectAndUpload');
document.querySelector('#collectVisible').onclick = () => collect('collectVisibleAndUpload');

function showRun(run) {
  currentRun = run;
  autoButton.disabled = !!run && ['running', 'waiting'].includes(run.status);
  autoButton.textContent = !run
    ? '开始自动采集'
    : run.status === 'paused'
    ? '继续自动采集'
    : run.status === 'waiting'
    ? '每日定时采集已启用'
    : '正在自动采集';

  pauseButton.style.display = run && ['running', 'waiting'].includes(run.status) ? 'block' : 'none';
  if (!run) {
    continuousStatus.textContent = '尚未开始。点击上方按钮后会自动采集并翻页。';
    return;
  }

  const wait = run.waitUntil ? ` · 下次 ${new Date(run.waitUntil).toLocaleString()}` : '';
  const tick = run.status === 'running' && run.nextTickAt ? ` · 下条约 ${new Date(run.nextTickAt).toLocaleTimeString()}` : '';
  const state = { running: '运行中', waiting: '定时等待', paused: '已暂停' }[run.status] || run.status;
  const pageProgress = run.pageMatched ? ` · 本页 ${run.pageProcessed || 0}/${run.pageMatched}` : '';
  continuousStatus.textContent = `${state} · 第 ${run.page} 页${pageProgress} · 累计新增 ${run.accepted} · 重复 ${run.duplicates} · 拒绝 ${run.rejected} · 详情失败 ${run.failed}${wait}${tick}\n${run.message || ''}`;
}

async function refreshRun() {
  try {
    try {
      const collector = await chrome.runtime.sendMessage({ type: 'collectorControl', platform: 'seek', action: 'status' });
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
        if (titleEl) titleEl.textContent = `任务状态：${labels[v.status] || v.status}`;

        if (syncBadge) {
          if (v.needsSetup) {
            syncBadge.textContent = '待连接控制台';
            syncBadge.style.color = '#e65100';
          } else {
            syncBadge.textContent = '连接信息已保存';
            syncBadge.style.color = '#2e7d32';
          }
        }
      }
    } catch {
      // collectorControl is optional fallback
    }

    showRun(await call('continuousState'));
    const { lifecycleReview } = await chrome.storage.local.get('lifecycleReview');
    const reviews = Object.values(lifecycleReview?.reviews || {});
    continuousStatus.textContent += `\n原链接复查 ${reviews.length} 条 · 已关闭 ${reviews.filter(x => x.status === 'closed').length} · 待复查 ${reviews.filter(x => x.status === 'unknown').length}${lifecycleReview?.pending ? ' · 有状态待同步' : ''}`;
    try {continuousStatus.textContent += '\n'+progressText(await call('seekProgress'));}
    catch {continuousStatus.textContent += '\n服务端今日进度：未知，暂时无法核对。历史回执不代表今日。';}
  } catch (error) {
    continuousStatus.textContent = error.message;
  }
}

autoButton.onclick = async () => {
  try {
    autoButton.disabled = true;
    continuousStatus.textContent = '正在启动自动采集…';
    showRun(await call(currentRun?.status === 'paused' ? 'resumeContinuous' : 'startContinuous'));
  } catch (error) {
    continuousStatus.textContent = error.message;
    if (/令牌|API|地址|设置/.test(error.message)) document.querySelector('#advanced').open = true;
    autoButton.disabled = false;
  }
};

pauseButton.onclick = async () => {
  try {
    showRun(await call('pauseContinuous'));
  } catch (error) {
    continuousStatus.textContent = error.message;
  }
};

document.querySelector('#clear').onclick = async () => {
  try {
    await call('clearSeen');
    status.textContent = '本地去重记录已清除；数据库记录不会删除。';
  } catch (error) {
    status.textContent = error.message;
  }
};

restore().catch(error => {
  status.textContent = error.message;
});
refreshRun();
setInterval(refreshRun, 5000);
