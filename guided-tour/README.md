# Guided Tours from real Odoo

ตัวเล่นภาพหลักฐานจาก Playwright ที่เปิด Odoo จริง ใช้ Shepherd.js **15.2.3** แบบ vendored พร้อม [license ต้นฉบับ](assets/vendor/SHEPHERD-LICENSE.md) ไม่มี backend หรือ Node build สำหรับตัวเล่น ไม่ใช้ Swiper และไม่ต่อ Odoo จาก GitHub Pages

สถาปัตยกรรม: Real Odoo → Playwright → screenshots / steps / relationships / final state → Python builder → static Shepherd replay

ดู [วิธีบันทึกและ build](../playwright-demo/README.md) หรือเปิดจาก root ด้วย `python3 -m http.server 8080` แล้วไป `http://localhost:8080/guided-tour/` ต้องเปิดผ่าน HTTP เพื่อโหลด JSON

เมื่อเปิด GitHub Pages จาก root repository จะใช้เส้นทาง `https://<username>.github.io/<repository>/guided-tour/` ได้ ไฟล์ใช้ relative URLs ทั้งหมดและไม่ต้องล็อกอิน Odoo

**Quick Tour** เล่นภาพ PROJECT70 ตามลำดับที่ Playwright เปิดจริง จบที่หน้าผลวงเงินใน Odoo ส่วนทัวร์สิทธิ์เล่นผลปฏิเสธการอ่านจริงจากบัญชี UAT ที่แยกจากข้อมูล PROJECT70 ป้าย persona หมายถึงบัญชีที่ใช้บันทึกภาพ **ไม่ใช่การสลับล็อกอินในเว็บ static**

ปุ่มเริ่มทัวร์ ย้อนกลับ ถัดไป ออก เริ่มใหม่ และความสัมพันธ์เอกสารใช้งานได้ทั้งเมาส์และคีย์บอร์ด ภาพและ hotspot ใช้สัดส่วนเดียวกันบนมือถือ มีลิงก์เปิดภาพเต็มเพื่ออ่านข้อความขนาดเล็ก พร้อมคำอธิบายและบทบรรยายเป็นข้อความ HTML

`generated/` เป็นผล build ห้ามแก้ข้อมูลหรือภาพเอง ใช้ `scripts/build-guided-tour.py <run-id>` จาก root เพื่อแทนที่ทั้งชุดหลังตรวจหลักฐาน ระบบตรวจ hash และความครบถ้วนก่อนเปลี่ยนไฟล์ Raw video และ trace อยู่ใน `playwright-demo/output/` ที่ไม่รวมใน Git

- [แหล่งหลักฐานและ run ID](generated/manifest.json)
- [ผลสรุปที่อ่านจาก Odoo](generated/final-state.json)
- [Storyboard ที่สร้างจาก metadata](generated/video-storyboard.md)
- [ข้อมูลเตรียมคำบรรยาย](generated/subtitle-hints.json)

**Dashboard BI Tour** ใช้ภาพและสถานะ KPI ที่ Playwright บันทึกจาก Dashboard จริงขณะเปลี่ยนตัวกรองโครงการและหน่วยงาน ทัวร์ static เล่นภาพต่อเนื่อง ไม่เชื่อม Odoo; ดู [รายละเอียด](../docs/dashboard-bi-demo.md)

**Full Creation Tour** เพิ่มอีกชุดใน `generated-fresh/` เป็นภาพของการสร้างเอกสารใหม่ผ่าน Playwright จริงตั้งแต่ Project จนถึงครุภัณฑ์ เลือกจาก dropdown หน้าเดียวกัน ดู [คู่มือ Fresh Creation](../docs/fresh-creation-demo.md) และ [storyboard แยก](generated-fresh/video-storyboard.md) Builder เลือกปลายทางจาก tour_type จึงไม่ทับ Quick/Permission ไม่มีการแก้ไขธุรกรรมจากหน้า static นี้

โครงการนี้เป็นการย้ายและสาธิต Odoo 20 Community โดยชุมชนอย่างอิสระ อ้างอิงซอร์สโอเพนซอร์ส NSTDA ERP-Government และ **ไม่ใช่รุ่นเผยแพร่อย่างเป็นทางการของ NSTDA** ใช้ AGPL-3.0 ตาม repository; Shepherd.js ต้นฉบับจาก npm `shepherd.js@15.2.3` แจกจ่ายแบบ dual license ตามไฟล์แนบ
