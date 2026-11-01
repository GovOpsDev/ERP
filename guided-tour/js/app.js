import {loadData} from './data.js';
import {state,resetState} from './state.js';
import {startTour,cancelTour} from './tour.js';
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=n=>new Intl.NumberFormat('th-TH').format(n)+' ฿';
let data,renderVersion=0;
const currentSteps=()=>data.steps.filter(s=>s.mode===state.mode);
function announce(text,error=false){$('#announcement').textContent=text;$('#announcement').className=error?'error':'';}
function docButton(key){const d=data.documents.find(d=>d.key===key);return `<button data-document="${esc(key)}">${esc(d?.ref||key)}</button>`;}
function showResult(){const r=data['final-state'];const fields=[['วงเงินโครงการ',money(r.budget.allocated)],['ผูกพัน',money(r.budget.committed)],['ใช้จริง',money(r.budget.actual)],['คงเหลือ',money(r.budget.remaining)],['ตรวจรับคอมพิวเตอร์',r.acceptance.quantity+' เครื่อง'],['ใบเรียกเก็บเงิน',r.bill.state],['ครุภัณฑ์',r.assets.count+' เครื่อง · '+money(r.assets.value)],[r.inventory.run_delta!==undefined?'รับสินค้าในรอบนี้':'สินค้าคงคลังรวม',(r.inventory.run_delta??r.inventory.total)+' หน่วย']];$('#result-grid').innerHTML=fields.map(([k,v])=>`<div class="metric"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');}
async function render(step=currentSteps()[state.index]){
  const version=++renderVersion;
  state.mode=step.mode;const steps=currentSteps();state.index=steps.findIndex(s=>s.id===step.id);
  $('#steps-nav').innerHTML=steps.map((s,i)=>`<button data-step="${s.id}" ${s.id===step.id?'aria-current="step"':''}>${String(i+1).padStart(2,'0')} · ${esc(s.title)}</button>`).join('');
  $('#tour-kind').textContent=data.directory==='generated-bi'?'PROJECT BUDGET · DASHBOARD BI':data.directory==='generated-fresh'?'FRESH CREATION · REAL ODOO REPLAY':state.mode==='permissions'?'PERMISSIONS · REAL ODOO REPLAY':'PROJECT70 · REAL ODOO REPLAY';
  $('#step-screen').textContent=step.screen;$('#step-title').textContent=step.title;$('#progress').textContent=`${state.index+1} / ${steps.length}`;
  const persona=data.personas.find(p=>p.id===step.persona);$('#persona').textContent=`Persona: ${persona?.label||step.persona} (${step.persona})`;
  $('#state').textContent=`สถานะ: ${step.state_before} → ${step.state_after}`;$('#record-kind').textContent=['inspect_persisted_document','inspect_fresh_result'].includes(step.operation)?'เปิดดูเอกสารที่บันทึกไว้จริง':step.mode==='permissions'?'ผลปฏิเสธการอ่านจริง':'สร้างและดำเนินการผ่าน Odoo UI จริง';
  $('#security-evidence').hidden=step.mode!=='permissions';$('#step-description').textContent=step.tooltip;$('#narration').textContent=step.narration;$('#step-code').textContent=step.id;
  $('#previous').disabled=state.index===0;$('#next').disabled=state.index===steps.length-1;
  const bi=data.directory==='generated-bi';$('#bi-state').hidden=!bi;
  if(bi){const f=step.dashboard_filters;$('#bi-filters').textContent=Object.keys(f).length?Object.values(f).join(' · '):'ทุกโครงการในบริษัทที่ผู้ใช้มีสิทธิ์';const labels=[['allocated_amount','จัดสรร'],['committed_amount','ผูกพัน'],['actual_amount','ใช้จริง'],['other_amount','รายการอื่น'],['available_amount','คงเหลือ']];$('#bi-kpis').innerHTML=labels.map(([k,v])=>`<span>${esc(v)}: ${esc(money(Math.trunc(step.kpis[k])))}</span>`).join(' · ');}
  $('#final-result').hidden=bi||step.screen!=='final-result';if(!bi)showResult();
  $('#budget-dashboard-evidence').hidden=step.screen!=='final-result'||data.directory!=='generated';
  $('#related-documents').innerHTML=step.relationships.length?step.relationships.map(docButton).join(''):'ไม่มีความสัมพันธ์ที่ส่งออกสำหรับขั้นตอนนี้';
  $('#relationship-list').innerHTML=data.relationships.map(r=>`<div class="relationship-row">${docButton(r.from)}<span aria-hidden="true">→</span>${docButton(r.to)}<small>${esc(r.type)} · ${esc(r.evidence)}</small></div>`).join('');
  const image=$('#evidence-image');image.alt=`ภาพ Odoo จริง: ${step.title}; ${step.tooltip}`;image.src=`${data.directory}/${step.screenshot}`;$('#full-image').href=image.src;
  try{await image.decode();}catch(error){if(version!==renderVersion)return;throw error;}if(version!==renderVersion)return;
  const box=step.target,hotspot=$('#evidence-hotspot');Object.assign(hotspot.style,{left:box.x*100+'%',top:box.y*100+'%',width:box.width*100+'%',height:box.height*100+'%'});hotspot.setAttribute('aria-label',step.tooltip);
  $('#screenshot-frame').style.aspectRatio=`${step.viewport.width}/${step.viewport.height}`;
}
function guard(action){return ()=>Promise.resolve().then(action).catch(e=>{console.error(e);announce(e.message,true);});}
async function run(mode){state.mode=mode;state.index=0;await startTour(currentSteps(),render,announce);}
async function openDocument(key){
  cancelTour();const step=data.steps.find(s=>s.document_ref===key&&s.mode==='main');
  if(step){await render(step);$('#step-title').focus();return;}
  const d=data.documents.find(d=>d.key===key);$('#relationships-panel').hidden=false;$('#relationships-toggle').setAttribute('aria-expanded','true');
  $('#document-detail').textContent=`${d.ref} · ${d.model} · สถานะ ${d.state} · มีข้อมูลอ้างอิงจากการรัน แต่ไม่มีภาพบันทึกเฉพาะรายการนี้`;
  $('#document-detail').scrollIntoView({block:'nearest'});
}
async function selectTour(value){
  cancelTour();data=await loadData(value==='fresh'?'generated-fresh':value==='bi'?'generated-bi':'generated');state.mode=value==='permissions'?'permissions':'main';state.index=0;
  await render();
}
async function main(){
  data=await loadData();
  await render();for(const id of ['start-tour','restart','relationships-toggle'])$('#'+id).disabled=false;
  $('#tour-selector').addEventListener('change',guard(()=>selectTour($('#tour-selector').value)));
  $('#start-tour').addEventListener('click',guard(()=>run(state.mode)));
  $('#restart').addEventListener('click',guard(async()=>{cancelTour();state.index=0;await render();announce('กลับไปขั้นตอนแรกแล้ว');}));
  $('#previous').addEventListener('click',guard(async()=>{cancelTour();state.index=Math.max(0,state.index-1);await render();}));
  $('#next').addEventListener('click',guard(async()=>{cancelTour();state.index=Math.min(currentSteps().length-1,state.index+1);await render();}));
  $('#relationships-toggle').addEventListener('click',()=>{const panel=$('#relationships-panel');panel.hidden=!panel.hidden;$('#relationships-toggle').setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden)panel.scrollIntoView({block:'start'});});
  document.addEventListener('click',event=>{const button=event.target.closest('button');if(button?.dataset.step)guard(async()=>{cancelTour();await render(data.steps.find(s=>s.id===button.dataset.step));})();// Native buttons provide Enter/Space keyboard behavior.
    if(button?.dataset.document)guard(()=>openDocument(button.dataset.document))();});
  announce('พร้อมสำรวจภาพบันทึกจาก Odoo จริง เลือกเริ่มทัวร์หรือเลือกขั้นตอนทางซ้าย');
}
main().catch(e=>{console.error(e);announce('โหลดหลักฐานไม่สำเร็จ: '+e.message,true);});
