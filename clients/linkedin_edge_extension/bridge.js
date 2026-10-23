/* Website messages never expose extension storage or permit arbitrary commands. */
(() => {
  const platform = 'linkedin';
  const origins = new Set(['http://localhost:3000','http://127.0.0.1:3000']);
  if (window !== window.top || !origins.has(location.origin) || location.pathname !== '/admin/imports') return;
  // Non-secret diagnostic only; never used to authorize a command.
  const mark = () => document.documentElement?.setAttribute('data-jobagg-' + platform + '-bridge', chrome.runtime.getManifest().version);
  if (document.documentElement) mark(); else document.addEventListener('DOMContentLoaded', mark, {once:true});
  const allowed = new Set(['status','start','pause','resume','sync','configure']);
  let pending = 0;
  window.addEventListener('message', async event => {
    const m = event.data;
    if (event.source !== window || event.origin !== location.origin
      || m?.type !== 'JOBAGG_COLLECTOR_REQUEST' || m.platform !== platform
      || typeof m.requestId !== 'string' || !/^[\w-]{1,100}$/.test(m.requestId)
      || !allowed.has(m.action) || pending >= 8) return;
    pending++;
    try {
      const reply = await chrome.runtime.sendMessage({type:'collectorControl',platform,action:m.action,
        ...(m.action === 'configure' ? {config:{apiUrl:m.config?.apiUrl,deviceToken:m.config?.deviceToken}} : {})});
      window.postMessage({type:'JOBAGG_COLLECTOR_RESPONSE',requestId:m.requestId,platform,
        ok:reply?.ok === true,...(reply?.ok ? {value:reply.value} : {error:reply?.error || '扩展未响应，请重新加载扩展后刷新本页。'})}, location.origin);
    } catch {
      window.postMessage({type:'JOBAGG_COLLECTOR_RESPONSE',requestId:m.requestId,platform,ok:false,
        error:'扩展连接已中断，请重新加载扩展后刷新本页。'}, location.origin);
    } finally { pending--; }
  });
})();
