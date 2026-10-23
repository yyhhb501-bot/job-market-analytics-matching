const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function popup() {
 const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{textContent:'',style:{},value:''});return nodes.get(id);};
 const context=vm.createContext({Date,document:{querySelector:node,getElementById:node},setInterval:()=>{},
  chrome:{storage:{local:{get:async()=>({}),set:async()=>{}}},runtime:{getManifest:()=>({version:'2.2.0'}),
   sendMessage:async()=>({ok:true,value:null})}}});
 vm.runInContext(fs.readFileSync(__dirname+'/popup.js','utf8'),context);return context;
}
test('the stored 24/200 receipt is historical and never rendered as current daily progress',()=>{
 const p=popup();const text=p.formatResult({received_count:1,accepted_count:1,progress:{today_valid:24,today_target:200}});
 assert.match(text,/历史结果/);assert.doesNotMatch(text,/24\/200|今日有效/);
});
test('current progress uses verified server values, while expired or failed checks are explicit',()=>{
 const p=popup(),value={today_valid:0,today_target:600,hour_valid:0,hour_limit:50};
 assert.match(p.progressText({value,checkedAt:Date.now(),fresh:true}),/服务端今日有效 0\/600/);
 const expired=p.progressText({value:{...value,today_valid:24,today_target:200},checkedAt:Date.now()-86400000,fresh:false,error:'离线'});
 assert.match(expired,/已过期/);assert.doesNotMatch(expired,/服务端今日有效/);
 const missing=p.progressText({value:null,error:'不可用'});assert.match(missing,/未知/);assert.doesNotMatch(missing,/0\/600/);
});
