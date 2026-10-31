"use strict";
const search = document.querySelector("#manual-search");
const sections = [...document.querySelectorAll("main section[id]")];
const status = document.querySelector("#search-status");
function filterSections() {
    const query = (search?.value || "").trim().normalize("NFC").toLocaleLowerCase("th");
    let matches = 0;
    for (const section of sections) {
        const visible = !query || section.textContent.normalize("NFC").toLocaleLowerCase("th").includes(query);
        section.hidden = !visible;
        document.querySelector(`nav a[href="#${section.id}"]`)?.toggleAttribute("hidden", !visible);
        matches += Number(visible);
    }
    if (status) status.textContent = query ? `พบ ${matches} หัวข้อจาก ${sections.length} หัวข้อ` : "ค้นหาจากข้อความในคู่มือนี้";
    document.querySelector(".empty-results")?.toggleAttribute("hidden", matches > 0);
}
search?.addEventListener("input", filterSections);
document.querySelector("#guide-select")?.addEventListener("change", event => {
    const destination = event.target.value;
    if (/^[a-z_]+\.html$/.test(destination)) window.location.assign(destination);
});
const navButton = document.querySelector("[data-nav-toggle]");
navButton?.addEventListener("click", () => {
    const open = document.querySelector(".sidebar").classList.toggle("open");
    navButton.setAttribute("aria-expanded", String(open));
});
for (const link of document.querySelectorAll("nav a[href^='#']")) {
    link.addEventListener("click", () => {
        for (const other of document.querySelectorAll("nav a")) other.classList.toggle("active", other === link);
        document.querySelector(".sidebar")?.classList.remove("open");
        navButton?.setAttribute("aria-expanded", "false");
    });
}
document.querySelector("[data-print]")?.addEventListener("click", () => window.print());
window.addEventListener("beforeprint", () => { for (const section of sections) section.hidden = false; });
window.addEventListener("afterprint", filterSections);
