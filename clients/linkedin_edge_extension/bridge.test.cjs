const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
for(const platform of ['linkedin','seek']) {
  const dir=__dirname.replace('linkedin_edge_extension',platform+'_edge_extension');
  test(platform+': control rejects foreign pages, frames and arbitrary commands',async()=>{
    const context=vm.createContext({URL,chrome:{runtime:{getURL:p=>'chrome-extension://test/'+p}}});
    vm.runInContext(fs.readFileSync(dir+'/controller.js','utf8'),context);
    const control=context.JobaggControl;let invoked=0;
    const driver={status:async()=>({platform,status:'idle'}),start:async()=>invoked++};
    const message={action:'start',platform};
    for(const sender of [
      {tab:{url:'https://evil.example/admin/imports'},url:'https://evil.example/admin/imports',frameId:0},
      {tab:{url:'http://localhost:3000/admin/imports'},url:'http://localhost:3000/admin/imports',frameId:1},
      {tab:{url:'http://localhost:3000/admin/imports'},url:'http://localhost:3000/elsewhere',frameId:0}
    ]) await assert.rejects(control.handle(message,sender,platform,driver));
    const sender={tab:{url:'http://localhost:3000/admin/imports'},url:'http://localhost:3000/admin/imports',frameId:0};
    await assert.rejects(control.handle({action:'executeScript',platform},sender,platform,driver));
    await control.handle(message,sender,platform,driver);assert.equal(invoked,1);
    assert.throws(()=>control.connection({apiUrl:'https://evil.example',deviceToken:'jagg_abc'}));
  });
  test(platform+': content bridge ignores cross-origin requests and does not echo configuration secrets',async()=>{
    let listener;const posts=[],calls=[];const w={};w.top=w;
    w.addEventListener=(_name,fn)=>listener=fn;w.postMessage=data=>posts.push(data);
    const context=vm.createContext({window:w,document:{documentElement:{setAttribute(){}}},location:{origin:'http://localhost:3000',pathname:'/admin/imports'},
      chrome:{runtime:{getManifest:()=>({version:'2.0.1'}),sendMessage:async message=>{calls.push(message);return {ok:true,value:{platform,status:'idle'}};}}}});
    vm.runInContext(fs.readFileSync(dir+'/bridge.js','utf8'),context);
    const data={type:'JOBAGG_COLLECTOR_REQUEST',platform,requestId:'test-1',action:'configure',config:{apiUrl:'http://localhost:8010',deviceToken:'jagg_secret'}};
    await listener({source:w,origin:'https://evil.example',data});assert.equal(calls.length,0);
    await listener({source:w,origin:'http://localhost:3000',data});assert.equal(calls.length,1);
    assert.equal(posts[0].ok,true);assert.ok(!JSON.stringify(posts).includes('jagg_secret'));
  });
}
