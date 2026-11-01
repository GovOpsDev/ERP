// Educational approximation only. ERP access is ultimately enforced by Odoo.
// Sources: erp_organization, erp_budget, erp_procurement, erp_contract and
// erp_inventory security/ir.access.csv and the Project demo setup guide.
const groupFor={project:'project',budget:'budget',request:'request',requisition:'procurement',purchase:'procurement',agreement:'contract',contract:'contract',acceptance:'acceptance',inventory:'inventory',issue:'inventory',bill:'finance',asset:'asset'};
export function canRead(person,doc){if(!person||!doc)return {allow:false,reason:'ไม่พบผู้ใช้หรือเอกสาร'};if(!person.companies.includes(doc.company))return {allow:false,reason:'บริษัทไม่อยู่ในขอบเขตที่อนุญาต'};
 // Native Project access is company and visibility based; do not assert an OU rule on it.
 if(doc.kind!=='project'&&doc.ou&&!person.ous.includes(doc.ou))return {allow:false,reason:'หน่วยงานไม่อยู่ในการมอบหมาย'};
 const need=groupFor[doc.kind];const allowed=person.capabilities.includes(need)||(doc.kind==='request'&&person.capabilities.includes('review'))||(doc.kind==='project'&&person.capabilities.includes('read'));
 return allowed?{allow:true,reason:'ผ่านขอบเขตบริษัท หน่วยงาน และบทบาทในตัวอย่าง'}:{allow:false,reason:'บทบาทจำลองไม่มีสิทธิ์อ่านเอกสารประเภทนี้'};}
export function canApprove(person,doc){const read=canRead(person,doc);if(!read.allow)return read;if(doc.kind!=='request')return {allow:false,reason:'ตัวอย่างนี้ทดสอบเฉพาะการทบทวนใบขอซื้อ'};if(!person.capabilities.includes('review')||!person.assigned_reviewer)return {allow:false,reason:'ไม่ใช่ผู้ทบทวนที่ได้รับมอบหมายในตัวอย่าง'};return {allow:true,reason:'ผ่านการตรวจผู้ทบทวนตัวอย่าง; กฎจริงขึ้นกับ tier และสถานะ'};}
export const securitySources=['projects/organization/addons/erp_organization/security/ir.access.csv','projects/budget/addons/erp_budget/security/ir.access.csv','projects/procurement/addons/erp_procurement/security/ir.access.csv','projects/contract/addons/erp_contract/security/ir.access.csv','projects/inventory/addons/erp_inventory/security/ir.access.csv'];
