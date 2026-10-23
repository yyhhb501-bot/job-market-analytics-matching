const test=require('node:test');
const assert=require('node:assert/strict');
const {PRESETS}=require('./presets.js');

test('nationwide presets target the requested countries',()=>{
  assert.equal(PRESETS['us-data'].location,'usa');
  assert.equal(PRESETS['au-nursing'].location,'australia');
});

test('presets include broad role families and safe pacing',()=>{
  assert.match(PRESETS['us-data'].keywords,/Data Scientist/);
  assert.match(PRESETS['us-data'].keywords,/Data Engineer/);
  assert.match(PRESETS['au-nursing'].keywords,/Registered Nurse/);
  assert.ok(Number(PRESETS['us-data'].delay)>=3);
  assert.equal(Number(PRESETS['us-data'].maxJobs),1000);
  assert.equal(Number(PRESETS['au-nursing'].maxPages),40);
  assert.equal(PRESETS['us-data'].strictTitle,true);
  assert.equal(PRESETS['au-nursing'].keywords,'Registered Nurse');
});
