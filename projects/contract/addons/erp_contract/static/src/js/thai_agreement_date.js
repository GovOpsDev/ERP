/** @odoo-module **/

import { user } from "@web/core/user";
import { registry } from "@web/core/registry";
import { DateTimeField, dateField } from "@web/views/fields/datetime/datetime_field";

const thaiDateFormatter = new Intl.DateTimeFormat("th-TH-u-ca-buddhist", {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
});

// Only changes the displayed date; Odoo's picker and stored Gregorian date remain intact.
class ThaiAgreementDateField extends DateTimeField {
    getFormattedValue(valueIndex, numeric = this.props.numeric) {
        const value = this.values[valueIndex];
        if (value && user.lang.toLowerCase().startsWith("th")) {
            const date = new Date(0);
            date.setUTCFullYear(value.year, value.month - 1, value.day);
            date.setUTCHours(0, 0, 0, 0);
            return thaiDateFormatter.format(date);
        }
        return super.getFormattedValue(valueIndex, numeric);
    }
}

registry.category("fields").add("thai_agreement_date", {
    ...dateField,
    component: ThaiAgreementDateField,
});
