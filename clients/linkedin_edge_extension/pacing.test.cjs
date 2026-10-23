const {test}=require('node:test');
const assert=require('node:assert/strict');
const P=require('./pacing.js');
test('daily target counts unique accepted IDs by Beijing date, excluding yesterday and future values',()=>{
 const now=Date.parse('2026-10-19T16:01:00Z');
 assert.equal(P.DAILY_TARGET,600);
 assert.equal(P.countDaily({old:'2026-10-19T15:59:59Z',today:'2026-10-19T16:00:00Z',
   future:'2026-10-19T16:02:00Z',invalid:'bad'},now),1);
 assert.equal(P.window(now).dayStart,Date.parse('2026-10-19T16:00:00Z'));
});
test('hourly budget is capped at 50 and cannot accumulate skipped hours',()=>{
 const daily={target:1200,windowStart:0};
 assert.equal(P.HOURLY_TARGET,50);
 assert.equal(Array.from({length:24},(_,i)=>P.allowance(daily,i)).reduce((a,b)=>a+b),1200);
 assert.equal(P.allowance(daily,P.slot(daily,20*P.HOUR)),50);
 const backfill={target:1000,windowStart:0};
 assert.equal(P.allowance(backfill,19),50);
 assert.equal(P.allowance(backfill,20),50);
});
test('posting dates use explicit metadata, never applicant or result counts',()=>{
 const now=Date.parse('2026-09-22T12:00:00Z');
 assert.equal(P.postedAt('Reposted 2 days ago · 150 applicants',now),'2026-09-20T12:00:00.000Z');
 assert.equal(P.postedAt('3 小时前 · 已有 50 位申请者',now),'2026-09-22T09:00:00.000Z');
 assert.equal(P.postedAt('150 applicants',now),null);
 assert.equal(P.postedAt('2026-09-23T00:00:00Z',now),null);
});
