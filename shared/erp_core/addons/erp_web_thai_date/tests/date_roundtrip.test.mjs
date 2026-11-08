// Use the same Luxon build as the deployed Odoo runtime; no extra npm packages.
// ODOO_LUXON_FILE=/tmp/odoo-luxon.js node tests/date_roundtrip.test.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';

assert(process.env.ODOO_LUXON_FILE, 'Set ODOO_LUXON_FILE to the deployed Odoo Luxon JS file');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.env.ODOO_LUXON_FILE, 'utf8'), sandbox);
const { DateTime, Settings } = sandbox.luxon;
Settings.defaultZone = 'Asia/Bangkok';
const source = fs.readFileSync(new URL('../static/src/thai_date.js', import.meta.url), 'utf8');
const { THAI_MONTHS, formatThaiDate, formatThaiDateTime, normalizeThaiDateInput } =
    await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const parseNormalized = value => DateTime.fromISO(normalizeThaiDateInput(value).replace(' ', 'T'));

test('all twelve months round trip without changing the original Gregorian value', () => {
    for (let month = 1; month <= 12; month++) {
        const original = DateTime.fromObject({ year: 2027, month, day: 14 });
        const iso = original.toISODate();
        const display = formatThaiDate(original);
        assert.equal(display, `14 ${THAI_MONTHS[month - 1]} 2570`);
        assert.equal(parseNormalized(display).toISODate(), iso);
        assert.equal(original.toISODate(), iso);
    }
});

test('current-year dates always include the full Buddhist year', () => {
    const today = DateTime.now();
    assert(formatThaiDate(today).endsWith(String(today.year + 543)));
});

test('leap days validate against Gregorian years after Buddhist conversion', () => {
    assert.equal(parseNormalized('29 ก.พ. 2567').toISODate(), '2024-02-29');
    assert.equal(parseNormalized('29 ก.พ. 2570').isValid, false);
    assert.equal(parseNormalized('31 เม.ย. 2570').isValid, false);
});

test('Thai digits, abbreviated months and explicit Buddhist numeric dates', () => {
    for (const input of ['๑๔ ก.พ. ๒๕๗๐', '14 กพ 2570', '14/02/2570', '14-2-2570', '14.2.2570']) {
        assert.equal(parseNormalized(input).toISODate(), '2027-02-14');
    }
});

test('Gregorian ISO, numeric input and native relative operations pass through', () => {
    for (const value of ['2027-02-14', '14/02/2027', '+3d', '+1w', 'not a date']) {
        assert.equal(normalizeThaiDateInput(value), value);
    }
    assert.equal(normalizeThaiDateInput('14 ก.พ. 2027'), '2027-02-14');
});

test('empty fields remain empty', () => {
    for (const value of [false, null, undefined, '']) {
        assert.equal(formatThaiDate(value), '');
        assert.equal(formatThaiDateTime(value), '');
        assert.equal(normalizeThaiDateInput(value), value);
    }
});

test('date-only values never shift day across timezone boundaries', () => {
    const date = DateTime.fromISO('2027-02-14', { zone: 'Pacific/Kiritimati' });
    assert.equal(formatThaiDate(date), '14 ก.พ. 2570');
    assert.equal(date.toISODate(), '2027-02-14');
});

test('datetimes cross midnight in the user timezone while preserving UTC', () => {
    const value = DateTime.fromISO('2027-02-13T20:30:45Z', { zone: 'utc' });
    assert.equal(formatThaiDateTime(value, { tz: 'Asia/Bangkok', showSeconds: true }), '14 ก.พ. 2570 03:30:45');
    assert.equal(formatThaiDateTime(value, { tz: 'America/Los_Angeles' }), '13 ก.พ. 2570 12:30');
    assert.equal(value.toISO(), '2027-02-13T20:30:45.000Z');
    assert.equal(parseNormalized('14 ก.พ. 2570 03:30:45').toUTC().toISO(), value.toISO());
});

test('time visibility and same-day range options retain native semantics', () => {
    const value = DateTime.fromISO('2027-02-14T13:30:45');
    assert.equal(formatThaiDateTime(value, { showTime: false }), '14 ก.พ. 2570');
    assert.equal(formatThaiDateTime(value, { showDate: false }), '13:30');
    assert.equal(formatThaiDateTime(value, { showSeconds: true }), '14 ก.พ. 2570 13:30:45');
});
