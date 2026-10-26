const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const ts=require('typescript');
function handler(fetcher) {
  const output=ts.transpileModule(fs.readFileSync(__dirname+'/../app/api/demo-match/route.ts','utf8'),
    {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
  class NextResponse extends Response {static json(value,options){return new NextResponse(JSON.stringify(value),options);}}
  const compiledModule={exports:{}};
  vm.runInNewContext(output,{exports:compiledModule.exports,process:{env:{API_BASE_URL:'http://internal-api:8000'}},
    TextDecoder,Uint8Array,AbortSignal,fetch:fetcher,
    require:name=>name==='next/server'?{NextResponse}:{sameOrigin:r=>r.headers.get('origin')==='http://localhost:3000'}});
  return compiledModule.exports.POST;
}
function request(value,origin='http://localhost:3000') {
  return new Request('http://localhost:3000/api/demo-match',{method:'POST',headers:{origin},body:JSON.stringify(value)});
}
test('invalid JSON shapes and cross-origin calls never reach the upstream',async()=>{
  let calls=0;const post=handler(async()=>{calls++;throw Error('must not call');});
  for(const value of [null,[],42,'text',{}, {resume:' '}]) assert.equal((await post(request(value))).status,400);
  assert.equal((await post(request({resume:'Python'},'https://evil.example'))).status,403);
  assert.equal(calls,0);
});
test('stream size is counted in UTF-8 bytes even without Content-Length',async()=>{
  let calls=0;const post=handler(async()=>{calls++;throw Error('must not call');});
  assert.equal((await post(request({resume:'文'.repeat(12000)}))).status,413);
  assert.equal(calls,0);
});
test('example mode selects only its fixed endpoint and forwards bounded public fields',async()=>{
  const post=handler(async(url,options)=>{
    assert.equal(url,'http://internal-api:8000/api/v1/demo/examples/match');assert.ok(options.signal);
    assert.deepEqual(JSON.parse(options.body),{resume:'Python SQL',country:'US',remote_type:null,limit:10});
    return new Response('{"data_scope":"illustrative_examples","results":[]}',{status:200});
  });
  const response=await post(request({resume:'Python SQL',country:'US',illustrative:true,deviceToken:'not-forwarded'}));
  assert.equal(response.status,200);assert.equal((await response.json()).data_scope,'illustrative_examples');
});
test('an unavailable backend returns an actionable response without exposing its error',async()=>{
  const response=await handler(async()=>{throw Error('private backend diagnosis');})(request({resume:'Python'}));
  assert.equal(response.status,503);assert.doesNotMatch(await response.text(),/private backend/);
});
