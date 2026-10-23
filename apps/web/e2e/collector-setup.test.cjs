const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const ts=require('typescript');
function handler(identity,fetcher,environment={}) {
  const output=ts.transpileModule(fs.readFileSync(__dirname+'/../app/api/collector/setup/route.ts','utf8'),
    {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  const module={exports:{}};
  const context={exports:module.exports,URL,AbortSignal,process:{env:{API_KEY:'server-only-secret',...environment}},
    fetch:fetcher || (async()=>({ok:true,json:async()=>({token:'jagg_device_token'})})),
    require:name=>name==='next/headers'?{cookies:async()=>({get:()=>({value:'signed'})})}:
      name==='next/server'?{NextResponse:{json:(body,options={})=>({body,status:options.status || 200,headers:options.headers})}}:
      {SESSION_COOKIE:'jagg_session',readSessionToken:async()=>identity,sameOrigin:r=>r.headers.get('origin')==='http://localhost:3000'}};
  vm.runInNewContext(output,context);return module.exports.POST;
}
const request=(platform='linkedin',origin='http://localhost:3000')=>new Request('http://localhost:3000/api/collector/setup',
  {method:'POST',headers:{origin,host:'localhost:3000','Content-Type':'application/json'},body:JSON.stringify({platform})});
test('setup requires an operator and rejects cross-origin requests and unknown platforms',async()=>{
  assert.equal((await handler(null)(request())).status,401);
  assert.equal((await handler({kind:'member'})(request())).status,401);
  assert.equal((await handler({kind:'operator'})(request('linkedin','https://evil.example'))).status,403);
  assert.equal((await handler({kind:'operator'})(request('arbitrary'))).status,400);
});

test('container URL is accepted only with matching local Origin and actual Host',async()=>{
  const post=handler({kind:'operator'});
  const req=(origin,host,forwarded)=>new Request('http://0.0.0.0:3000/api/collector/setup',{
    method:'POST',headers:{...(origin?{origin}:{}),host,...(forwarded?{'x-forwarded-host':forwarded}:{}),
      'Content-Type':'application/json'},body:JSON.stringify({platform:'seek'})});
  assert.equal((await post(req('http://localhost:3000','localhost:3000'))).status,200);
  assert.equal((await post(req('http://localhost:3000','evil.example','localhost:3000'))).status,403);
  assert.equal((await post(req('https://evil.example','localhost:3000'))).status,403);
  assert.equal((await post(req(null,'localhost:3000'))).status,403);
});
test('an existing valid LinkedIn device is reused to keep historical ownership and deduplication',async()=>{
  let calls=0;
  const result=await handler({kind:'operator'},async(url,options)=>{
    calls++;assert.ok(url.endsWith('/import/jobs?page_size=1'));
    assert.equal(options.headers.Authorization,'Bearer jagg_existing');return {ok:true};
  },{JOBAGG_DEVICE_TOKEN:'jagg_existing'})(request('linkedin'));
  assert.equal(calls,1);assert.equal(result.body.deviceToken,'jagg_existing');
});
test('setup keeps admin credentials server-side and returns only one device connection',async()=>{
  const result=await handler({kind:'operator'},async(_url,options)=>{
    assert.equal(options.headers['X-API-Key'],'server-only-secret');
    assert.equal(JSON.parse(options.body).platform,'seek');
    return {ok:true,json:async()=>({token:'jagg_device_token',unrelated:'hidden'})};
  })(request('seek'));
  assert.equal(result.status,200);assert.equal(result.body.deviceToken,'jagg_device_token');
  assert.equal(result.body.apiUrl,'http://localhost:8010');
  assert.ok(!JSON.stringify(result).includes('server-only-secret'));
  assert.equal(result.headers['Cache-Control'],'no-store');
});
