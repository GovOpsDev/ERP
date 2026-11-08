# GovOpsDev ERP — Thai Buddhist dates

Backend date fields for Thai-language users display full dates such as
**14 ก.พ. 2570**, including the year even when it is the current year.

- Applies to the shared Date, Datetime, Date Range and Relative Date widgets,
  plus the standard date/datetime formatter registry used by lists and Kanban.
- Editable fields accept Thai abbreviated months, Buddhist numeric dates and
  Thai digits. ISO dates, Gregorian numeric input and native relative-date
  operations remain available through Odoo's parser.
- Datetime values retain their time and user timezone. A date-only value never
  moves to a different day because of timezone conversion.
- Invalid dates revert through the native picker validation; clearing a field
  retains Odoo's normal empty value.
- Stored Gregorian dates, UTC timestamps, exports and date calculations retain
  their original values. Other UI languages retain native Odoo formatting.
- The calendar picker retains Odoo's Gregorian calendar navigation. This addon
  formats the field text; it does not replace the calendar component.

The addon depends on `erp_core` and `web` and installs automatically when both
dependencies are present. For an existing database, install
`erp_web_thai_date`, restart the web service and reload the browser assets.
It does not require changing individual module views.

Conversion regression cases are in `tests/date_roundtrip.test.mjs`. Use the
deployed Odoo runtime's `web/static/lib/luxon/luxon.js` as `ODOO_LUXON_FILE` and run
`node tests/date_roundtrip.test.mjs`. These tests cover all twelve months,
Buddhist/Gregorian round trips, leap days, empty dates, Thai digits and timezone
rollover. Input, picker and saving behavior must additionally be checked in the
actual Odoo browser.

AGPL-3.0 · [Source and issues](https://github.com/GovOpsDev/ERP/)
