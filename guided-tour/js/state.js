export const initialState=()=>({view:'project',document:null,persona:'interactive-demo',notice:null,noticeType:'',permissionResult:'เลือกการทดสอบด้านล่างเพื่อดูผลจำลอง',testState:{'PR-TABLE':'ร่าง'}});
export let state=initialState();
export function resetState(){state=initialState();return state}
