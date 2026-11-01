import Shepherd from '../assets/vendor/shepherd.mjs';
let active=null;
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function cancelTour(){if(active){const old=active;active=null;old.cancel();}}
export async function startTour(steps,prepare,onEnd){
  cancelTour();
  const tour=new Shepherd.Tour({useModalOverlay:true,defaultStepOptions:{cancelIcon:{enabled:true,label:'ออกจากทัวร์'},scrollTo:{behavior:'auto',block:'center'},classes:'gov-tour'}});
  active=tour;
  steps.forEach((s,index)=>tour.addStep({
    id:s.id,title:s.title,
    text:`<div class="step-id">${escape(s.id)} · ${index+1} / ${steps.length}</div><p>${escape(s.tooltip)}</p><p>Persona: ${escape(s.persona)}</p>`,
    attachTo:{element:'#evidence-hotspot',on:'bottom'},
    beforeShowPromise:async()=>{await prepare(s);const target=document.querySelector('#evidence-hotspot');if(!target?.getClientRects().length)throw new Error('ไม่พบจุดอธิบายในภาพ');},
    buttons:[...(index?[{text:'ย้อนกลับ',classes:'shepherd-button-secondary',action(){return this.back();}}]:[]),{text:index===steps.length-1?'เสร็จสิ้น':'ถัดไป',action(){return index===steps.length-1?this.complete():this.next();}}]
  }));
  tour.on('cancel',()=>{active=null;onEnd('ออกจากทัวร์แล้ว เลือกขั้นตอนเพื่อสำรวจต่อได้');});
  tour.on('complete',()=>{active=null;onEnd('จบทัวร์แล้ว ภาพและผลตรวจของขั้นตอนสุดท้ายแสดงอยู่ด้านล่าง');});
  try {await tour.start();}catch(error){cancelTour();throw error;}
  return tour;
}
