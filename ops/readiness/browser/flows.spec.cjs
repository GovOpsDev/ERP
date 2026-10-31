// PRODUCTION READINESS FIX: ordinary-role fixtures, actual UI lifecycle buttons.
const {test,expect}=require('@playwright/test');
const fs=require('fs'),path=require('path');
const evidence=process.env.READINESS_EVIDENCE_DIR;
const f=JSON.parse(fs.readFileSync(path.join(evidence,'fixture.json')));
const password=fs.readFileSync(process.env.READINESS_PASSWORD_FILE,'utf8').trim();
async function login(page,role){
 await page.goto('about:blank');await page.context().clearCookies();await page.goto('/web/login');
 const switcher=page.getByRole('button',{name:/Use another user/});
 await expect(page.locator('input[name=login]:visible').or(switcher).first()).toBeVisible();
 if(await switcher.isVisible()) await switcher.click();
 await page.locator('input[name=login]').fill(f.users[role].login);
 await page.locator('input[name=password]').fill(password);
 await page.getByRole('button',{name:'Log in',exact:true}).click();
 await expect(page.locator('.o_main_navbar')).toBeVisible({timeout:60000});
}
async function rpc(page,model,method,args=[],kwargs={}){
 const response=await page.request.post(`/web/dataset/call_kw/${model}/${method}`,{data:{jsonrpc:'2.0',method:'call',id:1,params:{model,method,args,kwargs}}});
 const body=await response.json();expect(body.error,JSON.stringify(body.error)).toBeFalsy();return body.result;
}
async function create(page,model,vals,kwargs={}){const r=await rpc(page,model,'create',[[vals]],kwargs);return Array.isArray(r)?r[0]:r;}
async function read(page,model,id,fields){return (await rpc(page,model,'read',[[id],fields]))[0];}
async function open(page,model,id){await page.goto(`/odoo/action-${f.actions[model]}/${id}`);await expect(page.locator('.o_form_view')).toBeVisible({timeout:60000});await expect(page.locator('.o_form_view .o_field_widget').first()).toBeVisible();}
async function action(page,method){
 let received=false;
 const response=page.waitForResponse(r=>r.url().includes('/web/dataset/call_button')&&r.request().postDataJSON()?.params?.method===method);
 response.then(()=>{received=true;},()=>{});
 const modal=page.getByRole('dialog');
 const scope=await modal.isVisible()?modal:page.locator('.o_form_view');
 await scope.locator(`button[name="${method}"]:visible`).first().click();
 if(method==='action_submit'){
  const confirm=page.getByRole('button',{name:'Submit Expense',exact:true});
  await expect.poll(async()=>received||await confirm.isVisible()).toBeTruthy();
  if(await confirm.isVisible()) await confirm.click();
 }
 const body=await (await response).json();expect(body.error,JSON.stringify(body.error)).toBeFalsy();
 if(method==='action_post' && body.result?.res_model==='validate.account.move'){
  const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
  const force=dialog.locator('.o_field_widget[name=force_post] input');if(await force.isVisible()) await force.check();
  const validation=page.waitForResponse(r=>r.url().includes('/web/dataset/call_button')&&r.request().postDataJSON()?.params?.method==='validate_move');
  await dialog.locator('button[name=validate_move]').click();
  const result=await (await validation).json();expect(result.error,JSON.stringify(result.error)).toBeFalsy();await expect(dialog).toBeHidden();
 }
 return body.result;
}
async function role(page,info,name){
 if(info.traceStarted){await page.context().tracing.stop();info.traceStarted=false;}
 await login(page,name);await page.context().tracing.start({screenshots:true,snapshots:true});info.traceStarted=true;
}
test.afterEach(async({context},info)=>{if(info.traceStarted)await context.tracing.stop(info.status!==info.expectedStatus?{path:info.outputPath('failure-trace.zip')}:{});});

test('Budget allocation plan and reviewed release in browser',async({page},info)=>{
 test.setTimeout(180000);await role(page,info,'budget');
 const year=f.browser_year;
 let periods=await rpc(page,'erp.budget.period','search_read',[[['company_id','=',f.company],['date_from','=',`${year}-01-01`]]],{fields:['id'],limit:1});
 const period=periods.length?periods[0].id:await create(page,'erp.budget.period',{name:'Browser fiscal 2027',company_id:f.company,date_from:'2027-01-01',date_to:'2027-12-31',release_policy:'formal'});
 const allocation=await create(page,'erp.budget.allocation',{name:'Browser reviewed allocation',company_id:f.company,period_id:period,line_ids:[[0,0,{organization_id:f.unit,analytic_id:f.analytics[0],fund_id:f.fund,allocated_amount:10000}]]});
 await open(page,'erp.budget.allocation',allocation);await action(page,'action_done');
 const doc=await read(page,'erp.budget.allocation',allocation,['state','plan_id','line_ids']);expect(doc.state).toBe('done');
 const plan=doc.plan_id[0];await open(page,'erp.budget.plan',plan);await action(page,'action_confirm');
 const cap=(await read(page,'erp.budget.plan',plan,['line_ids'])).line_ids[0];
 const control=await create(page,'erp.budget.control',{name:'Browser released capacity',company_id:f.company,period_id:period,organization_id:f.unit,analytic_id:f.analytics[0],level:'analytic',amount:10000});
 const release=await create(page,'erp.budget.kpi.release',{name:'Browser release',plan_line_id:cap,released_amount:10000,line_ids:[[0,0,{control_id:control}]]});
 await open(page,'erp.budget.kpi.release',release);await action(page,'action_submit');
 await role(page,info,'manager');await open(page,'erp.budget.kpi.release',release);await action(page,'action_approve');
 expect((await read(page,'erp.budget.kpi.release',release,['state'])).state).toBe('done');
 await open(page,'erp.budget.kpi.release',release);
 await page.screenshot({path:path.join(evidence,'uat-budget-reviewed-release.png'),fullPage:true});
 fs.writeFileSync(path.join(evidence,'budget-browser-flow.json'),JSON.stringify({period,allocation,plan,release,control}));
});

test('PR requisition PO acceptance bill actual and Asset with role transitions',async({page},info)=>{
 test.setTimeout(300000);await role(page,info,'requester');
 const rows=await rpc(page,'erp.procurement.request','search_read',[[['id','in',f.requests],['state','=','draft']]],{fields:['id'],limit:1});expect(rows.length).toBe(1);const request=rows[0].id;
 await open(page,'erp.procurement.request',request);await action(page,'action_submit');
 await role(page,info,'approver');await open(page,'erp.procurement.request',request);await action(page,'action_approve');
 await role(page,info,'procurement');await open(page,'erp.procurement.request',request);
 const reqAction=await action(page,'action_create_requisition');const requisition=reqAction.res_id;
 await rpc(page,'purchase.requisition','write',[[requisition],{vendor_id:f.vendor}]);
 await open(page,'purchase.requisition',requisition);await action(page,'action_confirm');
 const poAction=await action(page,'action_create_rfq');const po=poAction.res_id;
 await open(page,'purchase.order',po);await action(page,'button_confirm');
 const order=await read(page,'purchase.order',po,['order_line','state']);expect(order.state).toBe('purchase');
 await role(page,info,'inventory');
 const acceptance=await create(page,'erp.inventory.acceptance',{company_id:f.company,organization_id:f.unit,purchase_order_id:po,line_ids:[[0,0,{purchase_line_id:order.order_line[0],quantity:1}]]});
 await open(page,'erp.inventory.acceptance',acceptance);await action(page,'action_accept');
 expect((await read(page,'erp.inventory.acceptance',acceptance,['state'])).state).toBe('accept');
 await role(page,info,'finance');
 const bill=await create(page,'account.move',{move_type:'in_invoice',company_id:f.company,partner_id:f.vendor,journal_id:f.journal,invoice_date:'2026-10-01',date:'2026-10-01',erp_acceptance_id:acceptance,invoice_line_ids:[[0,0,{name:'Browser full flow bill',product_id:f.product,account_id:f.account,quantity:1,price_unit:100,tax_ids:[[5,0,0]],purchase_line_id:order.order_line[0],analytic_distribution:{[f.analytics[0]]:100}}]]});
 await open(page,'account.move',bill);await action(page,'action_post');expect((await read(page,'account.move',bill,['state'])).state).toBe('posted');
 await role(page,info,'asset');
 const acquisitions=await rpc(page,'erp.asset.asset','search_read',[[['bill_id','=',bill]]],{fields:['id','purchase_value','engine_asset_id']});expect(acquisitions.length).toBe(1);expect(acquisitions[0].purchase_value).toBe(100);
 await open(page,'erp.asset.asset',acquisitions[0].id);await action(page,'action_create_depreciation_asset');
 const engine=(await read(page,'erp.asset.asset',acquisitions[0].id,['engine_asset_id'])).engine_asset_id[0];
 await open(page,'account.asset',engine);await action(page,'validate');expect((await read(page,'account.asset',engine,['state'])).state).toBe('open');
 await page.screenshot({path:path.join(evidence,'uat-end-to-end-asset.png'),fullPage:true});
 await role(page,info,'budget');
 const lines=await rpc(page,'erp.budget.move','search_read',[[['document_key','=',`account.move:${bill}`],['move_type','=','actual']]],{fields:['amount','control_id']});expect(lines.length).toBe(2);expect(lines.every(l=>l.amount===100)).toBeTruthy();
 fs.writeFileSync(path.join(evidence,'financial-browser-flow.json'),JSON.stringify({request,requisition,po,acceptance,bill,asset:acquisitions[0].id,engine,actual:lines}));
});

test('Stock request submit fulfill receipt and return in browser',async({page},info)=>{
 test.setTimeout(180000);await role(page,info,'inventory');
 const request=await create(page,'erp.inventory.request',{company_id:f.company,organization_id:f.unit,warehouse_id:f.warehouse,location_id:f.extra.location,line_ids:[[0,0,{product_id:f.product,quantity:1,route_id:f.extra.route,fund_id:f.fund,analytic_id:f.analytics[0]}]]});
 await open(page,'erp.inventory.request',request);await action(page,'action_submit');await action(page,'action_approve');
 const line=(await read(page,'erp.inventory.request',request,['line_ids'])).line_ids[0];
 const moves=(await read(page,'erp.inventory.request.line',line,['move_ids'])).move_ids;
 const move=(await read(page,'stock.move',moves[0],['picking_id']));const picking=move.picking_id[0];
 await rpc(page,'stock.move','write',[moves,{quantity:1,picked:true}]);
 await open(page,'stock.picking',picking);await action(page,'button_validate');
 await open(page,'erp.inventory.request',request);if((await read(page,'erp.inventory.request',request,['state'])).state==='open') await action(page,'action_check_done');
 expect((await read(page,'erp.inventory.request',request,['state'])).state).toBe('done');
 await open(page,'stock.picking',picking);
 await action(page,'action_return');
 const returned=await rpc(page,'stock.picking','search_read',[[['return_id','=',picking]]],{fields:['id','move_ids']});expect(returned.length).toBe(1);
 await rpc(page,'stock.move','write',[returned[0].move_ids,{quantity:1,picked:true}]);await open(page,'stock.picking',returned[0].id);await action(page,'button_validate');
 expect((await read(page,'erp.inventory.request.line',line,['delivered_qty'])).delivered_qty).toBe(0);
});

test('Expense and employee advance submit approve and post in browser',async({page},info)=>{
 test.setTimeout(180000);await role(page,info,'finance');
 const ids=[];
 for(const advance of [false,true]){
 const amount=25+(await rpc(page,'hr.expense','search_count',[[['company_id','=',f.company]]]))/100;
 const id=await create(page,'hr.expense',{name:advance?'Browser employee advance':'Browser expense',company_id:f.company,employee_id:f.extra.employee,product_id:f.extra.service,account_id:advance?f.extra.advance_account:f.extra.expense_account,date:'2026-10-01',quantity:1,total_amount_currency:amount,currency_id:f.extra.currency,tax_ids:[[5,0,0]],analytic_distribution:{[f.analytics[0]]:100},erp_budget_period_id:f.period,erp_budget_organization_id:f.unit,erp_budget_fund_id:f.fund,erp_budget_analytic_id:f.analytics[0],erp_is_advance:advance});
 await open(page,'hr.expense',id);await action(page,'action_submit');await action(page,'action_approve');
 const record=await read(page,'hr.expense',id,['account_move_id','approval_state']);expect(record.account_move_id).toBeTruthy();
 await action(page,'action_open_account_move');await action(page,'action_post');
 expect((await read(page,'account.move',record.account_move_id[0],['state'])).state).toBe('posted');ids.push(id);
 }
 fs.writeFileSync(path.join(evidence,'expense-browser-flow.json'),JSON.stringify(ids));
});

test('Contract commitment bill refund and close through browser roles',async({page},info)=>{
 test.setTimeout(180000);await role(page,info,'contract');
 const contract=await create(page,'erp.contract.contract',{name:'Browser contract lifecycle',company_id:f.company,organization_id:f.unit,partner_id:f.vendor,journal_id:f.journal,line_ids:[[0,0,{name:'Browser contract service',product_id:f.extra.service,uom_id:f.extra.uom,quantity:2,price_unit:10,date_start:'2026-01-01',date_end:'2026-12-31',period_id:f.period,fund_id:f.fund,analytic_id:f.analytics[0],account_id:f.extra.expense_account}]]});
 await open(page,'erp.contract.contract',contract);await action(page,'action_commit_budget');
 const line=(await read(page,'erp.contract.contract',contract,['line_ids'])).line_ids[0];
 await role(page,info,'finance');
 const bill=await create(page,'account.move',{move_type:'in_invoice',company_id:f.company,partner_id:f.vendor,journal_id:f.journal,date:'2026-10-01',invoice_date:'2026-10-01',invoice_line_ids:[[0,0,{name:'Browser contract bill',product_id:f.extra.service,product_uom_id:f.extra.uom,account_id:f.extra.expense_account,quantity:1,price_unit:10,tax_ids:[[5,0,0]],erp_contract_line_id:line,analytic_distribution:{[f.analytics[0]]:100}}]]});
 await open(page,'account.move',bill);await action(page,'action_post');
 expect((await read(page,'account.move',bill,['state'])).state).toBe('posted');
 await action(page,'action_reverse');
 const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
 await dialog.locator('.o_field_widget[name=reason] input').fill('Readiness refund');
 await dialog.locator('button[name=refund_moves]').click();await expect(dialog).toBeHidden();
 const credits=await rpc(page,'account.move','search_read',[[['reversed_entry_id','=',bill]]],{fields:['id','state']});expect(credits.length).toBe(1);
 await open(page,'account.move',credits[0].id);await action(page,'action_post');expect((await read(page,'account.move',credits[0].id,['state'])).state).toBe('posted');
 await role(page,info,'contract');await open(page,'erp.contract.contract',contract);await action(page,'action_close_budget');
 expect((await read(page,'erp.contract.contract',contract,['commit_budget'])).commit_budget).toBe(false);
 fs.writeFileSync(path.join(evidence,'contract-refund-browser-flow.json'),JSON.stringify({contract,bill,refund:credits[0].id}));
});


test('Agreement activation revision and termination in browser',async({page},info)=>{
 test.setTimeout(180000);await role(page,info,'procurement');
 const approved=await rpc(page,'erp.procurement.request','search_read',[[['id','in',f.requests],['state','=','approved']]],{fields:['id','line_ids']});
 const requests=[];for(const candidate of approved){if(!(await rpc(page,'purchase.requisition.line','search_count',[[['erp_request_line_id','in',candidate.line_ids]]]))){requests.push(candidate);break;}}
 expect(requests.length).toBe(1);
 const req=(await rpc(page,'erp.procurement.request','action_create_requisition',[[requests[0].id]])).res_id;
 await rpc(page,'purchase.requisition','write',[[req],{vendor_id:f.vendor}]);await rpc(page,'purchase.requisition','action_confirm',[[req]]);
 const po=(await rpc(page,'purchase.requisition','action_create_rfq',[[req]])).res_id;
 await role(page,info,'contract');
 const id=await create(page,'erp.contract.agreement',{name:'Browser legal lifecycle',company_id:f.company,organization_id:f.unit,partner_id:f.vendor,purchase_order_id:po,start_date:'2026-01-01',end_date:'2027-12-31',signature_date:'2026-10-01'});
 await open(page,'erp.contract.agreement',id);await action(page,'action_activate');await action(page,'action_new_version');
 const revised=await read(page,'erp.contract.agreement',id,['state','version','revision_ids']);expect(revised.state).toBe('draft');expect(revised.version).toBe(2);expect(revised.revision_ids.length).toBe(1);
 await rpc(page,'erp.contract.agreement','write',[[id],{signature_date:'2026-10-01'}]);await open(page,'erp.contract.agreement',id);await action(page,'action_activate');await action(page,'action_terminate');
 expect((await read(page,'erp.contract.agreement',id,['state'])).state).toBe('inactive');
 await open(page,'erp.contract.agreement',id);
 await page.screenshot({path:path.join(evidence,'uat-agreement-history.png'),fullPage:true});
 fs.writeFileSync(path.join(evidence,'agreement-browser-flow.json'),JSON.stringify({agreement:id,po,revision:revised.revision_ids}));
});

test('Asset depreciation and disposal through role UI',async({page},info)=>{
 test.setTimeout(180000);await role(page,info,'asset');
 const candidates=await rpc(page,'erp.asset.asset','search_read',[[['company_id','=',f.company],['engine_asset_id','=',false],['state','=','draft']]],{fields:['id'],limit:1});expect(candidates.length).toBe(1);
 await open(page,'erp.asset.asset',candidates[0].id);await action(page,'action_create_depreciation_asset');const id=(await read(page,'erp.asset.asset',candidates[0].id,['engine_asset_id'])).engine_asset_id[0];await open(page,'account.asset',id);await action(page,'validate');
 await open(page,'account.asset',id);await page.getByRole('tab',{name:'Depreciation Board',exact:true}).click();
 await action(page,'create_move');
 const lines=await rpc(page,'account.asset.line','search_read',[[['asset_id','=',id],['type','=','depreciate'],['move_id','!=',false]]],{fields:['id','move_id','line_date']});expect(lines.length).toBeGreaterThan(0);
 await page.getByRole('button',{name:'Actions menu'}).click();await page.getByRole('menuitem',{name:'Remove Assets',exact:true}).click();
 const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
 await dialog.locator('.o_field_widget[name=date_remove] input').fill('12/31/2027');await dialog.locator('.o_field_widget[name=date_remove] input').press('Tab');
 await dialog.locator('.o_field_widget[name=remove_reason] input').fill('Readiness disposal');
 await dialog.locator('.o_field_widget[name=posting_regime]').click();await page.getByRole('menuitem',{name:'Residual Value',exact:true}).click();
 const posted=page.waitForResponse(r=>r.url().includes('/web/dataset/call_button')&&r.request().postDataJSON()?.params?.method==='remove');
 await dialog.locator('button[name=remove]').click();const result=await(await posted).json();expect(result.error,JSON.stringify(result.error)).toBeFalsy();await expect(dialog).toBeHidden();
 expect((await read(page,'account.asset',id,['state'])).state).toBe('removed');
 const removals=await rpc(page,'account.asset.line','search_read',[[['asset_id','=',id],['type','=','remove']]],{fields:['move_id']});expect(removals.length).toBe(1);
 await open(page,'account.move',removals[0].move_id[0]);await action(page,'action_post');expect((await read(page,'account.move',removals[0].move_id[0],['state'])).state).toBe('posted');await open(page,'account.asset',id);
 await page.screenshot({path:path.join(evidence,'uat-asset-disposed.png'),fullPage:true});
 fs.writeFileSync(path.join(evidence,'asset-disposal-browser-flow.json'),JSON.stringify({asset:id,depreciation:lines}));
});

test('AUC expense acquisition and transfer conserve value through UI',async({page},info)=>{
 test.setTimeout(240000);await role(page,info,'finance');
 const cost=75+(await rpc(page,'hr.expense','search_count',[[['company_id','=',f.company]]]))/100;
 const expense=await create(page,'hr.expense',{name:'Browser AUC capitalization',company_id:f.company,employee_id:f.extra.employee,product_id:f.extra.service,account_id:f.auc.account,date:'2026-10-01',quantity:1,total_amount_currency:cost,currency_id:f.extra.currency,tax_ids:[[5,0,0]],analytic_distribution:{[f.analytics[0]]:100},erp_budget_period_id:f.period,erp_budget_organization_id:f.unit,erp_budget_fund_id:f.fund,erp_budget_analytic_id:f.analytics[0],erp_asset_profile_id:f.auc.profile,erp_asset_organization_id:f.unit});
 await open(page,'hr.expense',expense);await action(page,'action_submit');await action(page,'action_approve');await action(page,'action_open_account_move');await action(page,'action_post');
 await role(page,info,'asset');const acquisition=(await rpc(page,'erp.asset.asset','search_read',[[['expense_id','=',expense]]],{fields:['id','engine_asset_id']}))[0];expect(acquisition).toBeTruthy();
 await open(page,'erp.asset.asset',acquisition.id);await action(page,'action_create_depreciation_asset');const source=(await read(page,'erp.asset.asset',acquisition.id,['engine_asset_id'])).engine_asset_id[0];
 await open(page,'account.asset',source);await action(page,'validate');expect((await read(page,'account.asset',source,['can_transfer'])).can_transfer).toBe(true);
 const wizard=await create(page,'account.asset.transfer',{company_id:f.company,date_transfer:'2026-10-31',transfer_journal_id:f.auc.journal,from_asset_ids:[[6,0,[source]]],to_asset_ids:[[0,0,{asset_name:'Browser capitalized asset',asset_profile_id:f.auc.destination_profile,quantity:1,price_unit:cost}]]},{context:{active_ids:[source],allowed_company_ids:[f.company]}});
 await open(page,'account.asset.transfer',wizard);await action(page,'transfer');
 const history=await rpc(page,'erp.asset.transfer.history','search_read',[[['source_ids','in',[source]]]],{fields:['id','value','move_id','destination_ids','organization_id']});expect(history.length).toBe(1);expect(history[0].value).toBe(cost);expect(history[0].organization_id[0]).toBe(f.unit);
 expect((await read(page,'account.asset',source,['state'])).state).toBe('removed');expect((await read(page,'account.move',history[0].move_id[0],['state'])).state).toBe('posted');
 const targets=await rpc(page,'account.asset','read',[history[0].destination_ids,['purchase_value']]);expect(targets.reduce((v,r)=>v+r.purchase_value,0)).toBe(cost);
 fs.writeFileSync(path.join(evidence,'asset-transfer-browser-flow.json'),JSON.stringify({expense,acquisition:acquisition.id,source,history}));
});
