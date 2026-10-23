const {test} = require('node:test');
const assert = require('node:assert/strict');
require('./schedule.js');
test('Beijing working window boundaries are independent of machine timezone', () => {
  for (const [time, active] of [['00:59:59',false],['01:00:00',true],['14:59:59',true],['15:00:00',false]]) {
    assert.equal(globalThis.SeekSchedule.window(Date.parse(`2026-09-23T${time}Z`)).active,active);
  }
  assert.equal(globalThis.SeekSchedule.window(Date.parse('2026-09-23T15:00:00Z')).nextStart,
    Date.parse('2026-09-24T01:00:00Z'));
});
