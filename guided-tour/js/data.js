export async function loadData() {
  const names=['manifest','steps','documents','relationships','personas','final-state'];
  const entries=await Promise.all(names.map(async name=>{
    const response=await fetch(`generated/${name}.json`);
    if(!response.ok)throw new Error(`ไม่พบหลักฐาน ${name} (${response.status})`);
    return [name,await response.json()];
  }));
  const data=Object.fromEntries(entries);
  if(data.manifest.status!=='PASS'||!data.steps.length)throw new Error('หลักฐานยังไม่ผ่านการตรวจ');
  return data;
}
