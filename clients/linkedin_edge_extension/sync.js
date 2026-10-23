/* Durable acknowledged outbox. Collection remains local when the API is down. */
(() => {
  const KEY = 'linkedinOutbox';
  const ALARM = 'linkedin-direct-sync';
  let mutation = Promise.resolve(), flushing = null;
  const locked = fn => { const next = mutation.catch(()=>{}).then(fn); mutation = next; return next; };
  const read = async () => (await chrome.storage.local.get(KEY))[KEY] || {items:{},acked:{}};
  const write = state => chrome.storage.local.set({[KEY]:state});
  const configured = async () => !!(await chrome.storage.local.get('collectorConnection')).collectorConnection?.deviceToken;
  async function configure(config) {
    await chrome.storage.local.set({collectorConnection:config});
    await locked(async()=>{const s=await read();s.authBlocked=false;s.lastError=null;
      for(const item of Object.values(s.items)) if(!item.rejected) item.retryAt=0;
      await write(s);});
  }
  function normalize(job, config = {}) {
    const raw = job.raw_payload || {};
    const country = job.country || job.search_country || raw.search_country
      || ({usa:'US',australia:'AU',melbourne:'AU',sydney:'AU',austin:'US'})[config.location];
    return {...job,source:'linkedin_user_import',country:country || null,
      state:job.state || raw.search_state || null,city:job.city || raw.search_city || null,
      raw_payload:{...raw,search_country:country || null,search_location:job.search_location || raw.search_location,
        occupation_group:job.occupation_group || raw.occupation_group}};
  }
  async function revision(job) {
    const bytes = await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(job)));
    return [...new Uint8Array(bytes)].map(x=>x.toString(16).padStart(2,'0')).join('');
  }
  async function capture(run) {
    if (!run) return;
    const entries = await Promise.all(Object.values(run.jobs || {}).map(async job=>{
      const normalized=normalize(job,run.config);return [String(job.source_job_id),normalized,await revision(normalized)];
    }));
    await locked(async()=>{const s=await read();
      for(const [id,job,rev] of entries) if(s.acked[id]!==rev && s.items[id]?.revision!==rev) {
        s.items[id]={job,revision:rev,key:`li-${id}-${rev}`.slice(0,80),attempts:0,retryAt:0};
      }
      await write(s);
    });
    await chrome.alarms.create(ALARM,{delayInMinutes:0.5,periodInMinutes:1});
  }
  async function request(path, body, key) {
    const {collectorConnection:c}=await chrome.storage.local.get('collectorConnection');
    if(!c?.deviceToken) throw Error('请先在采集控制台连接领英扩展。');
    const response=await fetch(`${c.apiUrl}/api/v1/import/${path}`,{method:'POST',
      headers:{'Content-Type':'application/json','Authorization':`Bearer ${c.deviceToken}`,...(key?{'Idempotency-Key':key}:{})},
      body:JSON.stringify(body),signal:AbortSignal.timeout(15000)});
    if(!response.ok) {const e=Error([401,403].includes(response.status)?'设备连接已失效，请重新连接。':
      response.status===429?'入库服务繁忙，稍后自动重试。':`入库服务暂时不可用（${response.status}），数据已保留。`);
      e.auth=[401,403].includes(response.status);throw e;}
    return response.json();
  }
  async function flushNow() {
    if(!await configured()) return summary();
    const s=await read(); if(s.authBlocked) return summary();
    // A job is its own idempotent unit. A changed revision never reuses an old receipt.
    const due=Object.entries(s.items).filter(([,i])=>!i.rejected && (i.retryAt || 0)<=Date.now()).slice(0,20);
    for(const [id,item] of due) {
      try {
        const result=await request('jobs',{source:'linkedin_user_import',jobs:[item.job]},item.key);
        const confirmed=result.received_count===1 && result.rejected_count===0
          && result.accepted_count+result.duplicate_count===1;
        await locked(async()=>{const latest=await read();
          if(confirmed) {
            latest.acked[id]=item.revision;latest.lastSyncAt=new Date().toISOString();latest.lastError=null;
            if(latest.items[id]?.revision===item.revision) delete latest.items[id];
          } else if(latest.items[id]?.revision===item.revision) {
            // Invalid postings remain inspectable; do not endlessly resend the same invalid data.
            latest.items[id].rejected=true;
            latest.items[id].error='服务端未接收该职位；原始记录已保留。';
            latest.lastError='部分职位未通过入库检查，原始记录已保留。';
          }
          await write(latest);
        });
      } catch(error) {
        await locked(async()=>{const latest=await read();const current=latest.items[id];
          if(current?.revision===item.revision) {
            current.attempts=(current.attempts || 0)+1;
            current.retryAt=Date.now()+Math.min(1800000,30000*2**Math.min(current.attempts,6));
          }
          latest.authBlocked=!!error.auth;
          latest.lastError=error.auth?'设备连接已失效，请重新连接。':'入库服务暂时不可用，已保留数据并安排重试。';
          await write(latest);
        });
        break;
      }
    }
    const next=await summary();
    if(!next.pendingSync) await chrome.alarms.clear(ALARM);
    else await chrome.alarms.create(ALARM,{delayInMinutes:1,periodInMinutes:1});
    return next;
  }
  function flush() { if(!flushing) flushing=flushNow().finally(()=>{flushing=null;});return flushing; }
  async function summary() {
    const s=await read();return {pendingSync:Object.keys(s.items).length,synced:Object.keys(s.acked).length,
      rejectedSync:Object.values(s.items).filter(i=>i.rejected).length,lastSyncAt:s.lastSyncAt || null,
      syncError:s.lastError || null,needsSetup:!await configured() || !!s.authBlocked};
  }
  globalThis.LinkedInSync={configured,configure,capture,flush,summary,normalize,
    observe:observation=>request('observations',{observations:[observation]})};
  chrome.alarms.onAlarm.addListener(alarm=>{if(alarm.name===ALARM) flush().catch(()=>{});});
})();
