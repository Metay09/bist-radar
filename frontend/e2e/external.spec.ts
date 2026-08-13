import {expect,test} from '@playwright/test';

const externalUrl=process.env.EXTERNAL_ACCEPTANCE_URL;
test.skip(!externalUrl,'External acceptance URL is opt-in');

test('yayındaki gerçek dashboard ekranları',async({page})=>{
  await page.setViewportSize({width:360,height:800});
  await page.goto(externalUrl!);
  await page.evaluate(()=>localStorage.setItem('bist-radar-tour-seen','1'));
  for(const [name,path] of [['radar','/'],['signals','/signals'],['portfolio','/portfolio'],['analysis','/analysis'],['system','/system']]){
    await page.goto(`${externalUrl}${path}`);
    await expect(page.locator('.desktop-sidebar')).toBeHidden();
    await expect(page.locator('.bottom')).toBeVisible();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('.skeleton')).toHaveCount(0);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth)).toBe(true);
    await expect(page.locator('pre')).toHaveCount(0);
    await expect(page.getByText('PERSIST_OPEN')).toHaveCount(0);
    await expect(page.getByText('PERSIST_CLOSED')).toHaveCount(0);
    await page.screenshot({path:`artifacts/android-360-${name}.png`,fullPage:true});
  }
  const symbols=await page.goto(`${externalUrl}/api/dashboard/candidates`).then(async()=>page.locator('body').textContent()).then(text=>JSON.parse(text||'[]').map((row:{symbol:string})=>row.symbol));
  expect(new Set(symbols).size).toBe(symbols.length);
  await page.goto(`${externalUrl}/symbol/ASTOR`);
  await expect(page.getByText('below_recent_swing_and_1_2_ATR')).toHaveCount(0);
  await expect(page.getByText(/Son tamamlanmış veriye göre/).first()).toBeVisible();
  await page.screenshot({path:'artifacts/android-360-astor-plan.png',fullPage:true});
  await page.getByRole('tab',{name:'Grafik'}).click();
  for(const label of ['Hedef 3','Hedef 2','Hedef 1','Alım','Stop','Referans'])await expect(page.locator('svg').getByText(label,{exact:false})).toBeVisible();
  await page.screenshot({path:'artifacts/android-360-astor-chart.png',fullPage:true});
  await page.setViewportSize({width:1440,height:900});
  await page.goto(externalUrl!);
  await expect(page.locator('.desktop-sidebar')).toBeVisible();
  await page.screenshot({path:'artifacts/desktop-radar.png',fullPage:true});
});
