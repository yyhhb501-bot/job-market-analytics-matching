// Fixed Beijing time, independent of browser/OS timezone.
globalThis.SeekSchedule = {
  interval: 72000,
  window(now = Date.now()) {
    const shifted = new Date(now + 8 * 3600000);
    const midnight = Date.UTC(shifted.getUTCFullYear(), shifted.getUTCMonth(), shifted.getUTCDate()) - 8 * 3600000;
    const start = midnight + 9 * 3600000;
    const end = midnight + 23 * 3600000;
    return {active: now >= start && now < end,
      nextStart: now < start ? start : start + 86400000,
      hour: Math.floor(now / 3600000), nextHour: (Math.floor(now / 3600000) + 1) * 3600000};
  }
};
