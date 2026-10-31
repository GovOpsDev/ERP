// PRODUCTION READINESS FIX: role-specific rendered forms and hostile RPC/IDs.
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const evidence = process.env.READINESS_EVIDENCE_DIR;
const fixture = JSON.parse(fs.readFileSync(path.join(evidence, 'fixture.json')));
const password = fs.readFileSync(process.env.READINESS_PASSWORD_FILE, 'utf8').trim();
async function login(page, role) {
  await page.context().clearCookies();
  await page.goto('/web/login', { waitUntil: 'domcontentloaded' });
  const switcher = page.getByRole('button', { name: /Use another user/ });
  await expect(page.locator('input[name=login]:visible').or(switcher).first()).toBeVisible();
  if (await switcher.isVisible()) await switcher.click();
  await page.locator('input[name=login]').fill(fixture.users[role].login);
  await page.locator('input[name=password]').fill(password);
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('.o_main_navbar')).toBeVisible({ timeout: 60000 });
}
async function rpc(page, model, method, args = [], kwargs = {}) {
  const response = await page.request.post(`/web/dataset/call_kw/${model}/${method}`, {
    data: { jsonrpc: '2.0', method: 'call', id: 1, params: { model, method, args, kwargs } },
  });
  expect(response.status()).toBe(200);
  return response.json();
}
async function openRecord(page, model, id) {
  expect(fixture.actions[model]).toBeTruthy();
  await page.goto(`/odoo/action-${fixture.actions[model]}/${id}`, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.o_form_view')).toBeVisible({ timeout: 60000 });
  await expect(page.locator('.o_form_view .o_field_widget').first()).toBeVisible();
  await expect(page.locator('.o_error_dialog')).toHaveCount(0);
}
test.afterEach(async ({ context }, info) => {
  if (info.status !== info.expectedStatus && info.traceStarted) {
    await context.tracing.stop({ path: info.outputPath('failure-trace.zip') });
  } else if (info.traceStarted) await context.tracing.stop();
});
const forms = [
  ['requester', 'erp.procurement.request', 'request', 'organization_id'],
  ['approver', 'erp.procurement.request', 'request', 'review_ids'],
  ['budget', 'erp.budget.control', null, 'available_amount'],
  ['procurement', 'purchase.order', 'po', 'order_line'],
  ['finance', 'account.move', 'bill', 'invoice_line_ids'],
  ['contract', 'erp.contract.contract', 'contract', 'line_ids'],
  ['inventory', 'erp.inventory.acceptance', 'acceptance', 'line_ids'],
  ['asset', 'erp.asset.asset', 'asset', 'purchase_value'],
  ['manager', 'erp.organization.unit', null, 'parent_id'],
];
for (const [role, model, record, field] of forms) {
  test(`rendered form: ${role}`, async ({ page, context }, info) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await login(page, role);
    await context.tracing.start({ screenshots: true, snapshots: true }); info.traceStarted = true;
    const id = record ? fixture.records[record] : role === 'budget' ? fixture.controls[0] : fixture.unit;
    await openRecord(page, model, id);
    await expect(page.locator(`.o_form_view .o_field_widget[name="${field}"]`)).toBeVisible();
    if (role === 'finance') await expect(page.locator('.o_field_widget[name=erp_acceptance_id]')).toBeVisible();
    await page.screenshot({ path: path.join(evidence, `uat-${role}.png`), fullPage: true });
    expect(errors).toEqual([]);
  });
}
for (const role of ['unauthorized', 'other_ou', 'foreign']) {
  test(`security: ${role} cannot read or mutate protected records`, async ({ page, context }, info) => {
    await login(page, role);
    await context.tracing.start({ screenshots: true, snapshots: true }); info.traceStarted = true;
    for (const [model, id] of [['account.move', fixture.records.bill], ['erp.procurement.request', fixture.records.request], ['erp.inventory.acceptance', fixture.records.acceptance], ['erp.asset.asset', fixture.records.asset], ['erp.contract.contract', fixture.records.contract]]) {
      expect((await rpc(page, model, 'read', [[id], ['name']])).error).toBeTruthy();
      expect((await rpc(page, model, 'write', [[id], { name: 'FORBIDDEN' }])).error).toBeTruthy();
    }
    expect((await rpc(page, 'erp.procurement.request', 'action_approve', [[fixture.records.request]])).error).toBeTruthy();
    expect((await rpc(page, 'account.move', 'action_post', [[fixture.records.bill]])).error).toBeTruthy();
    expect((await rpc(page, 'erp.asset.asset', 'action_create_depreciation_asset', [[fixture.records.asset]])).error).toBeTruthy();
    expect((await rpc(page, 'erp.budget.control', 'write', [[fixture.controls[0]], { amount: 99999999 }])).error).toBeTruthy();
    expect((await rpc(page, 'erp.budget.control.service', '_commit', [[], 1, '2026-10-01', 'forged'])).error).toBeTruthy();
    for (const attachment of fixture.attachments) {
      const response = await page.request.get(`/web/content/${attachment.id}?download=1`);
      expect([403,404]).toContain(response.status());
    }
    await page.goto(`/odoo/action-${fixture.actions['erp.procurement.request']}/${fixture.records.request}`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(/Access Error|not allowed|does not exist|Missing Record/i).first()).toBeVisible();
  });
}
test('attachment authorized download hashes and image fields', async ({ page }) => {
  await login(page, 'manager');
  for (const attachment of fixture.attachments) {
    const response = await page.request.get(`/web/content/${attachment.id}?download=1`);
    expect(response.status()).toBe(200);
    const body = await response.body();
    expect(body.length).toBe(attachment.bytes);
    expect(crypto.createHash('sha256').update(body).digest('hex')).toBe(attachment.sha256);
  }
  const image = await page.request.get(`/web/image/res.company/${fixture.company}/logo`);
  expect(image.status()).toBe(200);
  expect((await image.body()).length).toBeGreaterThan(100);
});
test('requester submit and assigned reviewer approve through the browser', async ({ page, context }, info) => {
  await login(page, 'requester');
  const candidates = await rpc(page, 'erp.procurement.request', 'search_read', [[['id','in',fixture.requests],['state','=','draft']]], { fields:['id'], limit:1 });
  expect(candidates.error).toBeFalsy(); expect(candidates.result.length).toBe(1);
  const id=candidates.result[0].id;
  await context.tracing.start({ screenshots:true,snapshots:true }); info.traceStarted=true;
  await openRecord(page,'erp.procurement.request',id);
  await page.locator('button[name=action_submit]').click();
  await expect(page.locator('button[name=action_submit]')).toBeHidden();
  expect((await rpc(page,'erp.procurement.request','action_approve',[[id]])).error).toBeTruthy();
  // Do not record credentials for the second role in a retained failure trace.
  await context.tracing.stop(); info.traceStarted=false;
  await login(page,'approver');
  await context.tracing.start({screenshots:true,snapshots:true});info.traceStarted=true;
  await openRecord(page,'erp.procurement.request',id);
  await page.locator('button[name=action_approve]').click();
  await expect(page.locator('button[name=action_approve]')).toBeHidden();
  const state=await rpc(page,'erp.procurement.request','read',[[id],['state']]);
  expect(state.result[0].state).toBe('approved');
});

test('security: role manager cannot grant System or self-delegate via RPC',async({page})=>{
 await login(page,'manager');const s=fixture.security;
 expect((await rpc(page,'erp.user.role','write',[[s.role],{group_ids:[[4,s.system_group]]}],{context:{role_sync:true,allowed_company_ids:[fixture.company]}})).error).toBeTruthy();
 expect((await rpc(page,'erp.user.role.delegation','create',[[{manager_id:fixture.users.manager.id,role_id:s.role,unit_id:fixture.unit}]])).error).toBeTruthy();
 expect((await rpc(page,'erp.user.role.mapping.delegation','create',[[{manager_id:fixture.users.manager.id,role_id:s.role,group_ids:[[4,s.system_group]]}]])).error).toBeTruthy();
 expect((await rpc(page,'res.users','write',[[fixture.users.manager.id],{group_ids:[[4,s.system_group]]}])).error).toBeTruthy();
});

test('security: crafted company context and employee controller IDs remain scoped',async({page})=>{
 await login(page,'foreign');
 expect((await rpc(page,'erp.organization.unit','read',[[fixture.unit],['name']],{context:{allowed_company_ids:[fixture.company]}})).error).toBeTruthy();
 const response=await page.request.post('/hr/get_org_chart',{data:{jsonrpc:'2.0',method:'call',id:1,params:{employee_id:fixture.extra.employee}}});
 const body=await response.json();expect(body.error || !body.result?.self).toBeTruthy();
 await login(page,'other_ou');
 const hidden=await page.request.post('/hr/get_org_chart',{data:{jsonrpc:'2.0',method:'call',id:1,params:{employee_id:fixture.extra.employee}}});
 const hiddenBody=await hidden.json();expect(hiddenBody.error || !hiddenBody.result?.self).toBeTruthy();
 expect((await rpc(page,'account.move','write',[[fixture.records.bill],{erp_budget_organization_id:fixture.unit}])).error).toBeTruthy();
});


test('deployment: authenticated WebSocket reaches evented worker',async({page})=>{
 await login(page,'manager');
 const result=await page.evaluate(()=>new Promise((resolve,reject)=>{
  const ws=new WebSocket(`ws://${location.host}/websocket?version=saas-19.5-1`);
  const deadline=setTimeout(()=>{ws.close();reject(new Error('WebSocket open timeout'));},10000);
  ws.onerror=()=>{clearTimeout(deadline);reject(new Error('WebSocket handshake failed'));};
  ws.onopen=()=>{clearTimeout(deadline);ws.close(1000);resolve('OPEN');};
 }));expect(result).toBe('OPEN');
});
