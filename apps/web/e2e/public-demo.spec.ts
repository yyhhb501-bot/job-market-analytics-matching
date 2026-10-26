import {expect,test} from "@playwright/test";

test("anonymous visitor can compute clearly labelled fictional matches",async({page})=>{
  await page.goto('/demo/match');
  await expect(page.getByRole('heading',{name:'简历匹配 · 免注册演示'})).toBeVisible();
  await page.getByRole('checkbox',{name:/使用虚构示例职位/}).check();
  await page.getByRole('button',{name:'注册护士 / Registered Nurse',exact:true}).click();
  await page.getByRole('button',{name:'开始匹配演示',exact:true}).click();
  await expect(page.getByText('Registered Nurse - Critical Care · 虚构示例',{exact:true})).toBeVisible();
  await expect(page.getByText(/本次使用虚构职位/)).toBeVisible();
  await expect(page.locator('a[href^="/jobs/-"]')).toHaveCount(0);
});

test("public data pages explain their evidence without requiring a session",async({page})=>{
  await page.goto('/collection');
  await expect(page.getByRole('heading',{name:/采集看板/})).toBeVisible();
  await expect(page.getByRole('button',{name:'刷新数据',exact:true})).toBeVisible();
  await expect(page.getByText('linkedin_user_import',{exact:true})).toBeVisible();
  await page.goto('/methodology');
  await expect(page.getByRole('heading',{name:'方法与可复现实验',exact:true})).toBeVisible();
  await expect(page.getByText(/尚无人工标注/)).toBeVisible();
  await expect(page.getByRole('cell',{name:'TF-IDF + Linear SVM',exact:true})).toBeVisible();
});

test("anonymous malformed proxy requests are handled and management stays protected",async({request})=>{
  expect((await request.post('/api/demo-match',{data:null})).status()).toBe(400);
  expect((await request.post('/api/proxy/match',{data:{resume:'Python'}})).status()).toBe(401);
});

test("public pages remain usable on a phone viewport",async({page})=>{
  await page.setViewportSize({width:390,height:844});
  for(const path of ['/demo/match','/collection','/methodology']) {
    await page.goto(path);
    await expect(page.getByRole('heading',{level:1})).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),path).toBe(true);
  }
});
