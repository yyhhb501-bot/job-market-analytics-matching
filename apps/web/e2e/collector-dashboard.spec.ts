import { expect, test } from "@playwright/test";
import { login } from "./helpers";

test.beforeEach(async ({ page }) => { await login(page); });

test.describe("Collector Dashboard Component", () => {
  test("one click configures only the missing device and starts both sources independently (mock bridge)",async({page})=>{
    let setupCalls=0;
    await page.route('**/api/collector/setup',async route=>{
      setupCalls++;expect(route.request().postDataJSON().platform).toBe('linkedin');
      await route.fulfill({json:{apiUrl:'http://localhost:8010',deviceToken:'jagg_mock_test_only'}});
    });
    await page.addInitScript(()=>{
      const states={linkedin:{needsSetup:true,status:'idle'},seek:{needsSetup:false,status:'idle'}};
      window.addEventListener('message',event=>{
        const req=event.data;
        if(event.source!==window||event.origin!==location.origin||req?.type!=='JOBAGG_COLLECTOR_REQUEST')return;
        if(req.platform!=='linkedin'&&req.platform!=='seek')return;
        const state=states[req.platform as 'linkedin'|'seek'];
        if(req.action==='configure')state.needsSetup=false;
        if(req.action==='start')state.status='running';
        window.postMessage({type:'JOBAGG_COLLECTOR_RESPONSE',requestId:req.requestId,platform:req.platform,ok:true,
          value:{platform:req.platform,...state,message:'模拟扩展：指令已确认',collected:0,pendingSync:0,synced:0,lastSyncAt:null,
            nextRunAt:null,canResume:false,requiresHuman:false,updatedAt:null,page:1}},location.origin);
      });
    });
    await page.goto('/admin/imports');
    await expect(page.getByTestId('status-linkedin')).toHaveText('空闲');
    await page.getByTestId('btn-start-all').click();
    await expect(page.getByTestId('status-linkedin')).toHaveText('运行中');
    await expect(page.getByTestId('status-seek')).toHaveText('运行中');
    expect(setupCalls).toBe(1);
    await expect(page.locator('body')).not.toContainText('jagg_mock_test_only');
  });

  test("displays offline state and reload guidance when bridge is absent", async ({ page }) => {
    // Navigate to /admin/imports. In development/e2e environment, the dashboard mounts at the top.
    await page.goto("/admin/imports");

    const dashboard = page.getByTestId("collector-dashboard");
    await expect(dashboard).toBeVisible();

    // Verify main action buttons exist
    await expect(page.getByTestId("btn-start-all")).toBeVisible();
    await expect(page.getByTestId("btn-pause-all")).toBeVisible();
    await expect(page.getByTestId("btn-refresh")).toBeVisible();

    // Initially or after timeout, sources report offline without bridge response
    // Wait for timeout (3.5s) to complete
    await expect(page.getByTestId("status-linkedin")).toHaveText("未连接", { timeout: 6000 });
    await expect(page.getByTestId("status-seek")).toHaveText("未连接", { timeout: 6000 });

    // Ensure metric values show dash "—" instead of confirmed 0
    await expect(page.getByTestId("metric-collected-linkedin")).toHaveText("—");
    await expect(page.getByTestId("metric-pending-linkedin")).toHaveText("—");
    await expect(page.getByTestId("metric-synced-linkedin")).toHaveText("—");

    // Missing injected bridge has a specific site-access instruction.
    await expect(page.getByTestId("error-linkedin")).toContainText("请允许扩展在此本机网站运行");

    // Collapsible help section is present and expandable
    const helpDetails = page.getByTestId("help-details");
    await expect(helpDetails).toBeVisible();
    await helpDetails.click();
    await expect(helpDetails).toHaveAttribute("open", "");
  });

  test("displays real metrics and status when bridge responds", async ({ page }) => {
    // Simulate extension content script bridge in the page environment
    await page.addInitScript(() => {
      window.addEventListener("message", (event) => {
        if (event.source !== window || event.origin !== window.location.origin) return;
        const req = event.data;
        if (!req || req.type !== "JOBAGG_COLLECTOR_REQUEST") return;

        if (req.platform === "linkedin") {
          window.postMessage(
            {
              type: "JOBAGG_COLLECTOR_RESPONSE",
              requestId: req.requestId,
              platform: "linkedin",
              ok: true,
              value: {
                platform: "linkedin",
                status: "waiting",
                message: "正常间隔等待，约 50 秒后读取下一条；本小时已访问 12/50 次。",
                collected: 120,
                dailyTarget: 200,
                todayCollected: 17,
                pendingSync: 5,
                synced: 115,
                lastSyncAt: new Date(Date.now() - 60000).toISOString(),
                nextRunAt: Date.now() + 50000,
                needsSetup: false,
                canResume: false,
                requiresHuman: false,
                updatedAt: new Date().toISOString(),
                page: 2,
              },
            },
            window.location.origin,
          );
        } else if (req.platform === "seek") {
          window.postMessage(
            {
              type: "JOBAGG_COLLECTOR_RESPONSE",
              requestId: req.requestId,
              platform: "seek",
              ok: true,
              value: {
                platform: "seek",
                status: "running",
                message: "正在逐条采集澳洲 Registered Nurse 职位。",
                collected: 45,
                pendingSync: 0,
                synced: 45,
                lastSyncAt: new Date(Date.now() - 120000).toISOString(),
                nextRunAt: null,
                needsSetup: false,
                canResume: false,
                requiresHuman: false,
                updatedAt: new Date().toISOString(),
                page: 3,
              },
            },
            window.location.origin,
          );
        }
      });
    });

    await page.goto("/admin/imports");

    // Check LinkedIn card
    await expect(page.getByTestId("status-linkedin")).toHaveText("等待中");
    await expect(page.getByTestId("metric-collected-linkedin")).toHaveText("120");
    await expect(page.getByTestId("daily-goal-linkedin")).toContainText("17 / 200");
    // Missing extension target uses the configured 600/day fallback.
    await expect(page.getByTestId("daily-goal-seek")).toContainText("600 条");
    await expect(page.getByTestId("metric-pending-linkedin")).toHaveText("5");
    await expect(page.getByTestId("metric-synced-linkedin")).toHaveText("115");
    await expect(page.getByTestId("time-next-linkedin")).toContainText("北京时间");

    // Check SEEK card
    await expect(page.getByTestId("status-seek")).toHaveText("运行中");
    await expect(page.getByTestId("metric-collected-seek")).toHaveText("45");
    await expect(page.getByTestId("metric-pending-seek")).toHaveText("0");
    await expect(page.getByTestId("metric-synced-seek")).toHaveText("45");

    // Pause button should be enabled because at least one is running/waiting
    await expect(page.getByTestId("btn-pause-all")).toBeEnabled();
  });

  test("shows human verification prompt when requiresHuman is true", async ({ page }) => {
    await page.addInitScript(() => {
      window.addEventListener("message", (event) => {
        if (event.source !== window || event.origin !== window.location.origin) return;
        const req = event.data;
        if (!req || req.type !== "JOBAGG_COLLECTOR_REQUEST") return;

        if (req.platform === "linkedin") {
          window.postMessage(
            {
              type: "JOBAGG_COLLECTOR_RESPONSE",
              requestId: req.requestId,
              platform: "linkedin",
              ok: true,
              value: {
                platform: "linkedin",
                status: "paused",
                message: "检测到安全验证（验证码），已自动暂停。",
                collected: 80,
                pendingSync: 2,
                synced: 78,
                lastSyncAt: null,
                nextRunAt: null,
                needsSetup: false,
                canResume: true,
                requiresHuman: true,
                updatedAt: new Date().toISOString(),
                page: 1,
              },
            },
            window.location.origin,
          );
        }
      });
    });

    await page.goto("/admin/imports");

    await expect(page.getByTestId("human-notice-linkedin")).toBeVisible();
    await expect(page.getByTestId("btn-resume-linkedin")).toHaveText("验证后继续");
  });
});
