"use strict";
let snapshot;
const $ = (id) => document.getElementById(id);
const number = (value) => Number(value).toLocaleString("zh-CN");
const date = (value) => value ? new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) + " 北京时间" : "无记录";
function element(tag, text, className) {
  const node = document.createElement(tag); if (text !== undefined) node.textContent = text;
  if (className) node.className = className; return node;
}
function row(target, values) { const tr = element("tr"); for (const value of values) tr.append(element("td", value)); target.append(tr); }
function render(data) {
  $("snapshot-time").textContent = "数据快照：" + date(data.generated_at) + " · 重新发布后更新，不随采集器实时变化";
  const metrics = [["库内记录",data.sources.reduce((n,s)=>n+s.internal_total,0)], ["可公开职位详情",data.sources.reduce((n,s)=>n+s.public_total,0)], ["LinkedIn 库内记录",data.sources.find(s=>s.source==="linkedin_user_import")?.internal_total??0], ["SEEK 库内记录",data.sources.find(s=>s.source==="seek_user_import")?.internal_total??0]];
  for (const [label,value] of metrics) { const card=element("div",undefined,"metric");card.append(element("strong",number(value)),element("span",label));$("metrics").append(card); }
  for (const source of data.sources) row($("sources"),[source.source,number(source.internal_total),number(source.public_total),number(source.today_new_bj),number(source.seven_day_new_bj),date(source.last_ingest_at)]);
  const states={online:"快照时最近有通信",stale:"历史通信已过期",offline:"没有近期通信",none:"无关联设备通信记录"};
  for (const upload of data.uploads) {
    const card=element("article",undefined,"upload");card.append(element("h3",upload.source.startsWith("linkedin")?"LinkedIn 领英":"SEEK 澳洲"),element("span",states[upload.collector_state]??"状态未知","status"));
    for (const text of ["最近回执："+date(upload.last_batch_completed_at),"最近批次：新增 "+(upload.last_batch_accepted??"—")+" / 重复 "+(upload.last_batch_duplicate??"—")+" / 拒绝 "+(upload.last_batch_rejected??"—"),"快照当日入库："+upload.today_accepted_bj+" / 目标 "+data.daily_target_per_source+" 条"]) card.append(element("p",text));$("uploads").append(card);
  }
  const end=new Date(new Date(data.generated_at).getTime()+8*3600000);const points=[];
  for(let i=6;i>=0;i--){const d=new Date(end);d.setUTCDate(d.getUTCDate()-i);const key=d.toISOString().slice(0,10);points.push({date:key,new_jobs:data.trend.find(p=>p.date===key)?.new_jobs??0});}
  const max=Math.max(1,...points.map(p=>p.new_jobs));
  for(const point of points){const item=element("div",undefined,"trend-row"),track=element("div",undefined,"bar-track"),bar=element("div",undefined,"bar");bar.style.width=(point.new_jobs/max*100)+"%";track.append(bar);item.append(element("span",point.date),track,element("span",number(point.new_jobs)));$("trend").append(item);}
  const method=data.methodology;
  if(method.available){$("experiment-meta").textContent=`训练 ${method.train_count} 条 / 测试 ${method.test_count} 条 · seed ${method.seed} · synthetic_only · 无真实人工标注`;
    const names={keyword_baseline:"关键词基线",pure_svm:"TF-IDF + Linear SVM",online_hybrid:"线上混合策略"};
    for(const s of method.strategies)row($("strategies"),[names[s.name]??s.name,s.occupation_macro_f1.toFixed(4),s.seniority_macro_f1.toFixed(4),s.overall_macro_f1.toFixed(4)]);
    $("dataset-hash").textContent="数据集 SHA-256："+method.dataset_sha256;
  }else $("experiment-meta").textContent="当前未提供可核对的实验产物。";
}
function tokens(text){return text.toLowerCase().match(/[a-z0-9]+/g)??[];}
function vector(text){const counts=new Map();for(const word of tokens(text)) counts.set(word,(counts.get(word)??0)+1);return counts;}
function cosine(a,b){let dot=0,aa=0,bb=0;for(const [key,n] of a){aa+=n*n;dot+=n*(b.get(key)??0);}for(const n of b.values())bb+=n*n;return aa&&bb?dot/Math.sqrt(aa*bb):0;}
$("sample-data").onclick=()=>{$("resume").value="Data Analyst with Python SQL pandas Tableau statistics dashboards and business analysis experience.";$("country").value="";};
$("sample-nurse").onclick=()=>{$("resume").value="Registered Nurse AHPRA acute care patient assessment ICU monitoring medication infection control clinical documentation.";$("country").value="AU";};
$("match-form").onsubmit=(event)=>{event.preventDefault();if(!snapshot){$("match-status").textContent="请等待快照加载完成。";return;}const resume=$("resume").value.trim();if(!resume){$("match-status").textContent="请先填写文本。";return;}const a=vector(resume),country=$("country").value;
  const results=snapshot.examples.filter(j=>!country||j.country===country).map(j=>({...j,score:cosine(a,vector(j.title+" "+j.description)),terms:[...new Set(tokens(j.title+" "+j.description))].filter(t=>a.has(t)).sort()})).sort((a,b)=>b.score-a.score);
  $("results").replaceChildren();for(const result of results){const card=element("article",undefined,"result");card.append(element("span","虚构教学示例 · 非真实招聘","badge"),element("h3",result.title),element("p",result.country+" · "+result.city+" · "+result.remote_type),element("div",(result.score*100).toFixed(1)+" / 100","score"),element("p","英文词项余弦 × 100，不是录用概率"),element("p","重合词项："+(result.terms.join(" · ")||"无")));$("results").append(card);}
  $("match-status").textContent=`已在本机计算 ${results.length} 个虚构示例。完整服务端引擎另含词项哈希、关键词及时间加权，本页为简化演示。`;
};
fetch("snapshot.json",{cache:"no-store"}).then(r=>{if(!r.ok)throw new Error("snapshot unavailable");return r.json();}).then(data=>{snapshot=data;render(data);}).catch(()=>{$("load-error").hidden=false;$("snapshot-time").textContent="当前无法读取快照";});
