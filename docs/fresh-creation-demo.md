# Fresh Creation Tour

สร้างธุรกรรมใหม่ผ่าน UI จริงของ Odoo โดยใช้ Playwright แล้วสร้าง static Shepherd tour จากหลักฐานชุดเดียวกัน ไม่ใช้ธุรกรรม PROJECT70 แทนเอกสารใหม่ และไม่มีการ insert ธุรกรรมลง PostgreSQL หรือเรียก ORM create/write/action แทนการกดหน้าจอ

## สถานการณ์และข้อมูลตั้งต้น

โครงการจัดหาอุปกรณ์คอมพิวเตอร์เพื่อสนับสนุนบริการดิจิทัลของ **สำนักงาน A สูงสุด** วงเงินใหม่ 300,000 THB ซื้อคอมพิวเตอร์ 6 เครื่อง เครื่องละ 30,000 บาท ยอดก่อนภาษี 180,000 บาท VAT 12,600 บาท รวมเจ้าหนี้ 192,600 บาท นโยบายงบของ fixture ใช้ยอดก่อนภาษี

ใช้ masters สังเคราะห์เดิม: หน่วยงาน `DEMO-DIGITAL`, สินค้า `PROJECT-COMPUTER`, ผู้ขายเทคโนโลยีตัวอย่าง, ปีงบประมาณ 2570, แหล่งเงิน Project ปี 2570, KPI ดิจิทัล, บัญชี `DEMO1500`, คลังเดิม และ asset profile แบบรายเครื่อง ไม่สร้าง masters ซ้ำทุก run

ทุก run สร้าง Project และบัญชีวิเคราะห์ใหม่ ชื่อมี `FRESH70-<timestamp>` ตามด้วยชื่อโครงการ มีงานและ Milestone ใหม่ เอกสารที่ระบบออกเลขให้อัตโนมัติคงเลขมาตรฐานและใส่ run ID ในเหตุผล รายการ หมายเหตุ หรือเอกสารอ้างอิง ความสัมพันธ์ใช้ ID ที่อ่านกลับจาก Odoo ไม่อาศัยชื่อเพียงอย่างเดียว

Project มาตรฐานไม่มีช่อง OU โดยตรง หน่วยงานเจ้าของกำหนดในวงเงินและเอกสารธุรกิจที่เชื่อมบัญชีวิเคราะห์ของ Project

## ฐานทดสอบและการทำซ้ำ

ใช้ **ฐานสำเนาแยก** เท่านั้น โปรแกรมตรวจชื่อฐานจริงจาก authenticated session ว่าตรง `ODOO_DEMO_DB` และขึ้นต้น `erp_fresh_` ก่อนสร้างข้อมูล ชื่อฐานอย่างเดียวไม่รับประกันความปลอดภัย ผู้ติดตั้งต้องยืนยันว่า endpoint เป็นระบบทดสอบที่อนุมัติแล้ว

รอบตรวจนี้แยก Odoo port 18079 และฐานรอบยืนยัน `erp_fresh_acceptance_20261101` จาก backup ของ demo เดิม พร้อม filestore ชื่อฐานตรงกัน ระบบเดิม port 18069 และฐาน `erp_restored_final_verified` ไม่ใช้รัน Full Creation อัตโนมัติ

การเพิ่ม analytic ใน allocation เดิมของสำเนาต้องมี coordinated KPI planning revisions ตามโมเดล Budget จึงเก็บวงเงินเดิมทุกแถวไว้เท่าเดิมแล้วเพิ่มมิติใหม่ 300,000 บาท ผู้ตรวจทานคนละบัญชีอนุมัติ revisions ก่อน activate และอนุมัติ release ของโครงการใหม่ นี่เป็นเหตุผลที่ห้ามรันบนฐานเดิมที่คนกำลังใช้งาน

ก่อนเริ่มมี backup แบบหยุด writer พร้อมตรวจ checksum ของ DB dump และ filestore แล้วใช้ `ops/readiness/backup_restore.py restore` สร้างฐานใหม่ เครื่องมือนี้ไม่ทับฐานที่มีอยู่ และไม่ลบ volume การกู้คืนรอบถัดไปให้ใช้ชื่อฐานใหม่และผูก endpoint ให้ตรงกัน

```bash
python3 ops/readiness/backup_restore.py restore \
  --database erp_fresh_example \
  --archive /private/verified-demo-backup
```

การรันซ้ำบนฐานสำเนาเดิมใช้ run ID ใหม่เสมอ และเพิ่มธุรกรรม/วงเงินของรอบนั้น ไม่ลบข้อมูลโดยอัตโนมัติ ผลสต็อกจึงเก็บทั้งยอดก่อน ยอดหลัง และ **delta 6 เครื่อง** ห้ามเรียกยอดคงคลังทั้งหมดว่าเป็นของ run เดียว การรันที่ล้มเหลวเก็บ `failure.json`, progress และ trace ไว้เพื่อวิเคราะห์ ไม่ resume โดยนำเอกสารเก่ามาอ้างว่าสร้างใหม่

## Personas

Fixture เดิมมี `interactive-demo` สำหรับบทบาทธุรกิจหลายด้าน และ `interactive-demo-reviewer` เป็นผู้ตรวจทานงบแยกต่างหาก Tier ของ PR/PO เดิมกำหนดผู้อนุมัติเป็น `interactive-demo` จึงใช้ตามการตั้งค่านั้น ไม่เพิ่มสิทธิ์ ไม่เปลี่ยน tier และไม่อ้างว่า PR/PO มีผู้อนุมัติแยกคนใน fixture นี้

รองรับ environment ของ budget, procurement, contract, inventory, finance, asset และ manager เป็นบัญชีแยกได้ หากระบบปลายทางกำหนดไว้จริง ต้องตั้ง tiers/OU assignments ล่วงหน้าตามนโยบายของระบบ แต่ละภาพระบุ login ที่ใช้จริง การอนุมัติงบของ reviewer เป็น checkpoint แยกพร้อมวิดีโอ session แยก

รหัสผ่านรับจาก environment เท่านั้นใน fresh scenario การเข้าสู่ระบบอยู่นอกบริบทที่บันทึกวิดีโอและ trace; storageState อยู่ใน memory ไม่เขียนลงไฟล์

## คำสั่ง

ตั้ง environment ตาม `playwright-demo/.env.example` ด้วย secret manager หรือ shell ที่ไม่พิมพ์รหัสผ่านลง log ไฟล์ `.env.example` เป็นเอกสารและไม่ถูกโหลดอัตโนมัติ

```bash
cd playwright-demo
npm ci
npm run demo:fresh
npm run demo:fresh:headed
npm run demo:fresh:record
```

สามคำสั่งนี้เป็นทางเลือก แต่ละคำสั่งสร้างธุรกรรมคนละ run หากต้องการวิดีโอให้เลือกคำสั่งสุดท้าย `DEMO_PACE_MS` ควบคุมการค้างภาพก่อน checkpoint เฉพาะโหมด record ค่าเริ่มต้น 1 วินาที โหมดปกติไม่ใส่ delay นี้

หลัง run ผ่าน จาก root repository:

```bash
python3 scripts/build-guided-tour.py <run-id> --validate-only --before-review
# ตรวจภาพทุกภาพและ selected JSON ว่าเป็น synthetic และไม่มีข้อมูลลับก่อนยืนยัน
python3 scripts/review-demo-evidence.py <run-id> --confirm-synthetic --confirm-no-credentials
python3 scripts/build-guided-tour.py <run-id>
cd playwright-demo
npm run test:static
```

Builder อ่าน `tour_type: fresh-creation` แล้วเขียนเฉพาะ `guided-tour/generated-fresh/` Quick/Permission อยู่ใน `guided-tour/generated/` เหมือนเดิม ไม่เขียน storyboard ทับกัน การเผยแพร่ยังต้องผ่าน privacy review ที่ผูกกับ hash ของ manifest ทุกครั้ง

## กระบวนงานและการตรวจยอด

1. สร้าง Project, analytic, task และ Milestone ผ่านหน้าปกติ
2. เพิ่มมิติจัดสรรงบ สร้างวงเงินและ release แผน KPI ผ่านผู้ตรวจทาน
3. สร้าง PR ส่ง ตรวจสอบ อนุมัติ และตรวจภาระผูกพัน
4. สร้าง requisition จาก PR ยืนยันและสร้าง RFQ มาตรฐาน
5. กำหนด Project และราคาใน PO สร้าง/ตรวจทาน/เปิดใช้ Agreement จาก PO แล้วอนุมัติ PO ตาม tier
6. ตรวจรับ 6 เครื่องก่อน validate incoming receipt ตามกติกา Work Acceptance ของระบบ
7. เปิด Vendor Bills และใช้ PO autocomplete มาตรฐาน เพื่อดึงผู้ขายและรายการจาก PO โดยตรง เชื่อม WA แล้วลงบัญชี
8. ตรวจครุภัณฑ์รายเครื่อง 6 รายการและสร้าง depreciation records ตาม profile เดิม คงสถานะร่าง ไม่มีการลงค่าเสื่อมหรือจ่ายเงินจริง
9. ปิดงานและทำเครื่องหมาย Milestone แล้วกลับไปดู Project และวงเงินคงเหลือ โครงการยังเปิดสำหรับติดตามการใช้งาน

Assertions ตรวจ FK ของ PR → requisition → PO → WA → bill → assets, Project/analytic, company/OU, ปริมาณสั่ง/รับ/ตรวจรับ/ตั้งหนี้เท่ากัน, สต็อกเพิ่ม 6 เครื่อง, bill posted และ asset รวม 180,000 บาท รวมถึงวงเงิน PROJECT70 เดิมไม่เปลี่ยน

งบสุดท้ายต้องเป็น `300000 = 0 committed + 180000 actual + 120000 remaining` ข้อตกลงใช้ **Agreement ของ PO** ไม่สร้าง recurring Contract ที่ผูกพันงบซ้ำสำหรับรายการเดียวกัน

## Evidence และข้อจำกัด

Output ส่วนตัวอยู่ใน `playwright-demo/output/<run-id>/`: manifest, steps, documents, relationships, personas, final-state, assertions, narration, PNGs และ WebM แยกตาม session Trace เก็บเฉพาะกรณีล้มเหลวหลัง login Raw video/trace/test DB/credentials ไม่รวม Git

Storyboard และ subtitle timing hints สร้างจาก steps เดียวกันใน `generated-fresh/` การค้างภาพเป็น pacing สำหรับตัดต่อ ไม่ใช่คำบรรยาย SRT ที่ sync เสียงแล้ว ยังไม่สร้างเสียง ไม่ upload วิดีโอ ไม่ push และไม่เปิด public tunnel

ระหว่างสำรวจพบ UI blockers ที่แก้ในซอร์สชุดนี้: ตัวกรอง plan line ที่ติดวงจร company-related, ทางเปิดฟอร์ม planning ย่อย และชื่อ asset เมื่อบิล native มี description ว่าง การทดสอบ regression ใช้ฐานสำเนาเท่านั้น ไม่ติดตั้งการแก้เหล่านี้ลง runtime เดิม port 18069 อัตโนมัติ


## ผลตรวจรับรอบล่าสุด — 1 พฤศจิกายน 2569

**PASS** ทั้ง fresh Odoo workflow และ static Full Creation Tour รายละเอียดผลตรวจและเลขเอกสารอยู่ใน [รายงานการตรวจรับ](fresh-creation-validation.md)

Run `FRESH70-20261101T105234882Z` ใช้เวลา 135.738 วินาที มี 27 checkpoints และใช้บัญชีจริง 2 บัญชี วงเงิน 300,000 บาท ใช้จริง 180,000 บาท คงเหลือ 120,000 บาท รับสินค้าเพิ่ม 6 เครื่องและสร้าง acquisition 6 รายการ
