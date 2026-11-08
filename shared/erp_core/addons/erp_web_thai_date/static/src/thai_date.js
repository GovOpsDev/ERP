/** @odoo-module **/

export const THAI_MONTHS = Object.freeze([
    'ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.',
    'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.',
]);

/** Format calendar parts only; never change the date object's calendar or year. */
export function formatThaiDate(value) {
    return value ? `${value.day} ${THAI_MONTHS[value.month - 1]} ${value.year + 543}` : '';
}

export function formatThaiDateTime(value, options = {}) {
    if (!value) {
        return '';
    }
    const date = value.setZone(options.tz || 'default');
    const parts = [];
    if (options.showDate !== false) {
        parts.push(formatThaiDate(date));
    }
    if (options.showTime !== false) {
        parts.push(date.toFormat(options.showSeconds ? 'HH:mm:ss' : 'HH:mm'));
    }
    return parts.join(' ');
}

/**
 * Convert explicit Thai / Buddhist input to Gregorian ISO for Odoo's parser.
 * Other input (ISO, Gregorian numeric dates, smart dates, relative operations)
 * passes through to the native parser. Invalid dates stay invalid there.
 */
export function normalizeThaiDateInput(value) {
    if (!value) {
        return value;
    }
    const latin = value.replace(/[๐-๙]/g, digit => String(digit.charCodeAt(0) - 0x0E50)).trim();
    const match = latin.match(/^(\d{1,2})\s+([^\s\d]+)\s+(\d{4})(\s+\d{1,2}:\d{2}(?::\d{2})?)?$/);
    let day, month, year, time = '';
    if (match) {
        month = THAI_MONTHS.findIndex(name => name.replaceAll('.', '') === match[2].replaceAll('.', '')) + 1;
        if (!month) {
            return latin;
        }
        [, day, , year] = match;
        time = match[4] || '';
    } else {
        const numeric = latin.match(/^(\d{1,2})[/.\-](\d{1,2})[/.\-](2[4-9]\d{2})(\s+\d{1,2}:\d{2}(?::\d{2})?)?$/);
        if (!numeric) {
            return latin;
        }
        [, day, month, year] = numeric;
        time = numeric[4] || '';
    }
    year = Number(year);
    if (year >= 2400) {
        year -= 543;
    }
    return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}${time}`;
}
