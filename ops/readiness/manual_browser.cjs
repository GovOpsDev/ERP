// Read-only end-to-end checks for the documentation addon; credentials stay in files.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
function option(name) { const i=process.argv.indexOf('--'+name); assert(i>=0,'Missing --'+name); return process.argv[i+1]; }
const base=option('base-url').replace(/\/$/,'');
const login=option('login');
const passwordFile=option('password-file');
const evidence=option('evidence-dir');fs.mkdirSync(evidence,{recursive:true,mode:0o700});
const addon=path.resolve(__dirname,'../../shared/erp_core/addons/erp_user_manual/static/manual');
const guides=JSON.parse(fs.readFileSync(path.join(addon,'guides.json')));
(async()=>{
 const browser=await chromium.launch({headless:true});
 const page=await browser.newPage({viewport:{width:1285,height:885}});
 const report={status:'RUNNING',pages:[],menuActions:[],menuClicks:[],mobile:[],search:[],pageErrors:[]};
 page.on('pageerror',e=>report.pageErrors.push(e.message));
 try {
  await page.goto(base+'/web/login',{waitUntil:'domcontentloaded'});
  await page.locator('input[name=login]').fill(login);
  await page.locator('input[name=password]').fill(fs.readFileSync(passwordFile,'utf8').trim());
  await page.locator('button[type=submit]').click();
  await page.locator('.o_main_navbar').waitFor({timeout:60000});
  const menus=await (await page.request.get(base+'/web/webclient/load_menus?lang=th_TH')).json();
  const list=Object.values(menus).filter(v=>v && typeof v==='object');
  for(const guide of guides){
   const menu=list.find(v=>v.xmlid==='erp_user_manual.menu_manual_'+guide.key);
   assert(menu,'Menu not visible: '+guide.key);
   const root=list.find(v=>v.xmlid===guide.parent);assert(root,'App root not visible: '+guide.key);
   assert.equal(menu.appID,root.id);assert.equal(menu.name,'คู่มือการใช้งาน');
   const response=await page.request.post(base+'/web/action/load',{data:{jsonrpc:'2.0',method:'call',params:{action_id:menu.actionID},id:1}});
   const body=await response.json();assert(!body.error,'Action load failed: '+guide.key);
   assert.equal(body.result.type,'ir.actions.act_url');assert.equal(body.result.target,'new');
   assert.equal(body.result.url.split('?')[0],'/erp_user_manual/static/manual/'+guide.key+'.html');
   report.menuActions.push(guide.key);
   await page.goto(base+'/odoo/action-'+root.actionID+'?menu_id='+root.id,{waitUntil:'domcontentloaded'});
   await page.locator('.o_main_navbar').waitFor({timeout:60000});
   if(guide.key==='dashboards'){
    await page.locator('.o_spreadsheet_dashboard_action .o_renderer').waitFor({state:'visible',timeout:60000});
    await page.locator('.dashboard-loading-status').waitFor({state:'hidden',timeout:15000});
   }
   const nav=page.locator('.o_menu_sections');
   let manual=page.locator('[data-menu-xmlid="erp_user_manual.menu_manual_'+guide.key+'"]:visible');
   if(!await manual.isVisible()){
    const more=nav.locator('.o_menu_sections_more, .o-dropdown--menu-toggler').last();
    if(await more.isVisible())await more.click();
    manual=page.locator('[data-menu-xmlid="erp_user_manual.menu_manual_'+guide.key+'"]:visible');
   }
   await manual.waitFor({state:'visible',timeout:15000});
   const popupPromise=page.waitForEvent('popup',{timeout:15000});await manual.click();
   const popup=await popupPromise;await popup.waitForLoadState('domcontentloaded');
   assert(popup.url().includes('/'+guide.key+'.html'),'Wrong guide opened: '+guide.key);
   assert.equal((await popup.locator('h1').innerText()).trim(),guide.title);await popup.close();
   report.menuClicks.push(guide.key);console.log('MENU_CLICK_PASS',guide.key);
  }
  for(const guide of [{key:'index',title:'คู่มือการใช้งาน'},...guides]){
   const response=await page.goto(base+'/erp_user_manual/static/manual/'+guide.key+'.html',{waitUntil:'networkidle'});
   assert.equal(response.status(),200);assert.equal((await page.locator('h1').innerText()).trim(),guide.title);
   const images=await page.locator('img').evaluateAll(es=>es.map(e=>({src:e.getAttribute('src'),ok:e.complete && e.naturalWidth>0})));
   assert(images.every(i=>i.ok),'Broken image: '+guide.key+JSON.stringify(images));
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Desktop overflow: '+guide.key);
   report.pages.push(guide.key);
   if(guide.key!=='index'){
    await page.locator('#manual-search').fill('ไม่พบข้อความXYZ987');
    await page.locator('.empty-results').waitFor({state:'visible'});
    await page.locator('#manual-search').fill('');await page.locator('main section').first().waitFor({state:'visible'});report.search.push(guide.key);
   }
   if(['agreements','budget','organization'].includes(guide.key)){
    await page.screenshot({path:path.join(evidence,guide.key+'-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Mobile overflow: '+guide.key);
    await page.locator('[data-nav-toggle]').click();await page.locator('#manual-search').waitFor({state:'visible'});
    await page.locator('[data-nav-toggle]').click();
    await page.screenshot({path:path.join(evidence,guide.key+'-mobile.png')});
    await page.emulateMedia({media:'print'});assert.equal(await page.locator('.sidebar').isVisible(),false);
    await page.emulateMedia({media:'screen'});await page.setViewportSize({width:1285,height:885});report.mobile.push(guide.key);
   }
   console.log('HTML_GUIDE_PASS',guide.key,images.length);
  }
  assert.deepEqual(report.pageErrors,[]);report.status='PASS';
 }catch(e){report.status='FAIL';report.error=e.message;await page.screenshot({path:path.join(evidence,'failure.png')}).catch(()=>{});throw e;
 }finally{fs.writeFileSync(path.join(evidence,'report.json'),JSON.stringify(report,null,2)+'\n');await browser.close();}
})().catch(e=>{console.error(e.stack);process.exit(1)});
