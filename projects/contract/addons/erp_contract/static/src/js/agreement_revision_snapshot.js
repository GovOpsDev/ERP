/** @odoo-module **/

import { Component, useProps } from "@odoo/owl";
import { user } from "@web/core/user";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

function plainText(value) {
    if (typeof value !== "string") return "";
    // A template is inert: old snapshot HTML is displayed as text, never executed.
    const template = document.createElement("template");
    template.innerHTML = value.replace(/<\/(p|div|li|h[1-6])\s*>|<br\s*\/?\s*>/gi, "$&\n");
    return template.content.textContent.trim();
}

class AgreementRevisionSnapshot extends Component {
    static template = "erp_contract.AgreementRevisionSnapshot";
    props = useProps(standardFieldProps);

    get snapshot() {
        const value = this.props.record.data[this.props.name];
        return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    }
    get hasSnapshot() { return Object.keys(this.snapshot).length > 0; }
    get empty() { return _t("Not specified"); }
    value(key, kind = "text") {
        const value = this.snapshot[key];
        if (!value) return this.empty;
        if (kind === "reference") {
            return typeof value === "object" ? String(value.name || (value.id ? `#${value.id}` : this.empty)) : String(value);
        }
        if (kind === "date") {
            const match = typeof value === "string" && /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
            if (!match) return this.empty;
            const date = new Date(0);
            date.setUTCFullYear(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
            date.setUTCHours(0, 0, 0, 0);
            return new Intl.DateTimeFormat(user.lang.toLowerCase().startsWith("th") ? "th-TH-u-ca-buddhist" : user.lang, {
                day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
            }).format(date);
        }
        return plainText(value) || this.empty;
    }
    get groups() {
        return [
            { title: _t("Legal Administration"), rows: [
                [_t("Stage"), "stage_id", "reference"], [_t("Type"), "type_id", "reference"],
                [_t("Subtype"), "subtype_id", "reference"], [_t("Assigned User"), "assigned_user_id", "reference"],
                [_t("Company Contact"), "company_contact_id", "reference"], [_t("Partner Contact"), "partner_contact_id", "reference"],
                [_t("Notification Address"), "notification_address_id", "reference"],
            ] },
            { title: _t("Signatures and Review"), rows: [
                [_t("Company Signatory"), "company_signed_user_id", "reference"], [_t("Company Signature Date"), "company_signed_date", "date"],
                [_t("Partner Signatory"), "partner_signed_user_id", "reference"], [_t("Partner Signature Date"), "partner_signed_date", "date"],
                [_t("Review Date"), "to_review_date", "date"], [_t("Reviewed By"), "reviewed_user_id", "reference"],
                [_t("Reviewed Date"), "reviewed_date", "date"], [_t("Approved By"), "approved_user_id", "reference"],
                [_t("Approved Date"), "approved_date", "date"],
            ] },
            { title: _t("Legal Content"), rows: [
                [_t("Description"), "description", "text"], [_t("Parties"), "parties", "text"],
                [_t("Special Terms"), "special_terms", "text"],
            ] },
        ].map(group => ({...group, rows: group.rows.map(([label, key, kind]) => ({key, label, value: this.value(key, kind)}))}));
    }
    get items() {
        const data = Array.isArray(this.snapshot.items) ? this.snapshot.items : [];
        const types = { recital: _t("Recital"), section: _t("Section"), clause: _t("Clause"), appendix: _t("Appendix") };
        return data.filter(item => item && typeof item === "object").map((item, index) => {
            const section = data.find(other => other && other.id === item.section_id);
            return {
                key: index, name: String(item.name || this.empty), title: String(item.title || this.empty),
                kind: types[item.kind] || String(item.kind || this.empty),
                section: section ? String(section.name || `#${section.id}`) : item.section_id ? `#${item.section_id}` : this.empty,
                sequence: item.sequence ?? this.empty,
                active: item.active ? _t("Active") : _t("Inactive"),
                content: plainText(item.content) || this.empty,
            };
        });
    }
}

registry.category("fields").add("agreement_revision_snapshot", {
    component: AgreementRevisionSnapshot,
    supportedTypes: ["json"],
});
