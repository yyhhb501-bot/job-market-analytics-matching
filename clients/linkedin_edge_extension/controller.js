/* Narrow, authenticated transport shared by the two standalone extensions. */
(() => {
  const actions = new Set(['status','start','pause','resume','sync','configure']);
  function localPage(value) {
    try {
      const url = new URL(value);
      return ['http://localhost:3000','http://127.0.0.1:3000'].includes(url.origin)
        && url.pathname === '/admin/imports';
    } catch { return false; }
  }
  function trusted(sender) {
    return sender.tab ? sender.frameId === 0 && localPage(sender.url) && localPage(sender.tab.url)
      : sender.url === chrome.runtime.getURL('popup.html');
  }
  function connection(raw) {
    let url;
    try { url = new URL(raw?.apiUrl); } catch { throw Error('本地入库地址无效，请重新连接。'); }
    if (!['http://localhost:8010','http://127.0.0.1:8010'].includes(url.origin)
      || url.pathname !== '/' || url.search || url.hash || url.username || url.password) {
      throw Error('一键采集只连接本机 8010 端口。');
    }
    if (typeof raw?.deviceToken !== 'string' || !/^jagg_[\w-]+$/.test(raw.deviceToken)
      || raw.deviceToken.length > 256) throw Error('设备连接信息无效，请重新连接。');
    return {apiUrl:url.origin,deviceToken:raw.deviceToken};
  }
  function requiresHuman(run) {
    return run?.status === 'paused' && /验证码|安全验证|安全检查|人工验证|登录|challenge|captcha|checkpoint|authwall|human|429|rate limit|访问频率|请求过多/i.test(run.message || '');
  }
  async function handle(message, sender, platform, driver) {
    if (!trusted(sender)) throw Error('该页面没有采集控制权限。');
    if (message.platform !== platform || !actions.has(message.action)) throw Error('不支持的采集操作。');
    if (message.action === 'configure') {
      await driver.configure(connection(message.config));
    } else if (message.action !== 'status') {
      await driver[message.action]();
    }
    return driver.status();
  }
  globalThis.JobaggControl = {localPage,trusted,connection,requiresHuman,handle};
})();
