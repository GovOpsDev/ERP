// Activated only for the prior-baseline deployment/rollback smoke.
const {test,expect}=require('@playwright/test');const fs=require('fs'),path=require('path'),crypto=require('crypto');
const enabled=process.env.READINESS_ROLLBACK==='1';
test('prior baseline seven domains and attachment hashes',async({page})=>{
 test.skip(!enabled,'Separate rollback acceptance invocation');test.setTimeout(180000);
 const f=JSON.parse(fs.readFileSync(path.join(process.env.READINESS_EVIDENCE_DIR,'rollback-smoke-fixture.json')));
 await page.goto('/web/login');const other=page.getByRole('button',{name:/Use another user/});await expect(page.locator('input[name=login]:visible').or(other).first()).toBeVisible();if(await other.isVisible())await other.click();
 await page.locator('input[name=login]').fill(f.login);await page.locator('input[name=password]').fill(fs.readFileSync(process.env.READINESS_PASSWORD_FILE,'utf8').trim());await page.getByRole('button',{name:'Log in',exact:true}).click();await expect(page.locator('.o_main_navbar')).toBeVisible({timeout:60000});
 const websocket=await page.evaluate(()=>new Promise((resolve,reject)=>{const ws=new WebSocket(`ws://${location.host}/websocket?version=saas-19.5-1`);const timeout=setTimeout(()=>{ws.close();reject(new Error('WebSocket timeout'));},10000);ws.onerror=()=>{clearTimeout(timeout);reject(new Error('WebSocket failed'));};ws.onopen=()=>{clearTimeout(timeout);ws.close(1000);resolve(true);};}));expect(websocket).toBe(true);
 // Activate all explicitly granted fixture companies through the native session cookie.
 await page.context().addCookies([{name:'cids',value:f.companies.join('-'),url:'http://127.0.0.1:18069'}]);
 for(const r of f.records){await page.goto(`/odoo/action-${r.action}/${r.id}`);await expect(page.locator('.o_form_view')).toBeVisible();await expect(page.locator('.o_form_view .o_field_widget').first()).toBeVisible();await expect(page.locator('.o_error_dialog')).toHaveCount(0);}
 for(const a of f.attachments){const res=await page.request.get(`/web/content/${a.id}?download=1`);expect(res.status(),`attachment ${a.id}`).toBe(200);const body=await res.body();expect(body.length).toBe(a.bytes);expect(crypto.createHash('sha256').update(body).digest('hex')).toBe(a.sha256);}
 await page.screenshot({path:path.join(process.env.READINESS_EVIDENCE_DIR,'rollback-seven-domain-smoke.png'),fullPage:true});
});
