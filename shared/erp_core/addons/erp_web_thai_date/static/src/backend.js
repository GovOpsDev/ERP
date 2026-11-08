/** @odoo-module **/

import { useLayoutEffect } from '@web/owl2/utils';
import { onWillDestroy } from '@odoo/owl';
import { datetimePickerService } from '@web/core/datetime/datetimepicker_service';
import { registry } from '@web/core/registry';
import { user } from '@web/core/user';
import { patch } from '@web/core/utils/patch';
import { DateTimeField } from '@web/views/fields/datetime/datetime_field';
import { RelativeDateField } from '@web/views/fields/relative_date/relative_date_field';
import { formatThaiDate, formatThaiDateTime, normalizeThaiDateInput } from './thai_date';

const isThai = () => user.lang?.toLowerCase().startsWith('th');

// Covers native date, datetime and daterange fields, including subclasses.
patch(DateTimeField.prototype, {
    getFormattedValue(index, numeric = this.props.numeric) {
        if (!isThai()) {
            return super.getFormattedValue(index, numeric);
        }
        const value = this.values[index];
        if (!value) {
            return '';
        }
        if (this.field.type === 'date') {
            return formatThaiDate(value);
        }
        return formatThaiDateTime(value, {
            showSeconds: this.props.showSeconds,
            showTime: this.props.showTime,
            showDate: !this.props.showTime || index !== 1 || !this.values[0] || !this.values[0].hasSame(value, 'day'),
        });
    },
    getPlaceholder(fieldName) {
        if (isThai() && !this.props.placeholder && this.picker.activeInput === fieldName) {
            return '14 ก.พ. 2570' + (this.field.type === 'datetime' ? ' 13:30' : '');
        }
        return super.getPlaceholder(fieldName);
    },
});

patch(RelativeDateField.prototype, {
    get diffString() {
        return isThai() ? formatThaiDate(this.props.record.data[this.props.name]) : super.diffString;
    },
    get formattedValue() {
        return isThai() ? formatThaiDate(this.props.record.data[this.props.name]) : super.formattedValue;
    },
    get numericValue() {
        return isThai() ? formatThaiDate(this.props.record.data[this.props.name]) : super.numericValue;
    },
});

// Native lists and other callers that use the field formatter registry.
for (const type of ['date', 'datetime']) {
    const original = registry.category('formatters').get(type);
    const format = (value, options = {}) => isThai()
        ? (type === 'date' ? formatThaiDate(value) : formatThaiDateTime(value, options))
        : original(value, options);
    Object.assign(format, original);
    registry.category('formatters').add(type, format, { force: true });
}

// Keep the native picker, date constraints, timezone handling and save workflow.
// Only translate the input's text at the boundary to/from Odoo's own parser.
patch(datetimePickerService, {
    start(...args) {
        const service = super.start(...args);
        const nativeCreate = service.create.bind(service);
        service.create = (params, options) => {
            if (!isThai() || params.format) {
                return nativeCreate(params, options);
            }
            let manager;
            let destroyed = false;
            const listeners = new Map();
            const getInputs = () => params.getInputs?.() || [];
            const displayInputs = () => {
                if (!manager || destroyed) {
                    return;
                }
                const state = manager.state;
                const values = Array.isArray(state.value) ? state.value : [state.value];
                getInputs().forEach((input, index) => {
                    if (input?.tagName !== 'INPUT') {
                        return;
                    }
                    input.value = state.type === 'date' ? formatThaiDate(values[index])
                        : formatThaiDateTime(values[index], { tz: state.tz, showSeconds: params.showSeconds ?? true });
                    if (!listeners.has(input)) {
                        const onKeydown = event => {
                            if (event.key === 'Escape') {
                                queueMicrotask(displayInputs);
                            }
                        };
                        input.addEventListener('keydown', onKeydown);
                        listeners.set(input, onKeydown);
                    }
                });
            };
            const wrapped = Object.create(params);
            wrapped.onWillParseValues = values => {
                const normalized = values.map(value => value && normalizeThaiDateInput(value));
                getInputs().forEach((input, index) => {
                    if (input?.tagName === 'INPUT') {
                        input.value = normalized[index] || '';
                    }
                });
                return params.onWillParseValues?.(normalized);
            };
            wrapped.onChange = (...values) => {
                params.onChange?.(...values);
                displayInputs();
            };
            wrapped.onApply = async (...values) => {
                await params.onApply?.(...values);
                displayInputs();
            };
            wrapped.onClose = (...values) => {
                params.onClose?.(...values);
                displayInputs();
            };
            manager = nativeCreate(wrapped, options);
            const destroy = manager.destroy;
            const cleanup = () => {
                destroyed = true;
                for (const [input, listener] of listeners) {
                    input.removeEventListener('keydown', listener);
                }
                listeners.clear();
            };
            manager.destroy = () => {
                cleanup();
                destroy();
            };
            if (options?.useOwlHooks) {
                useLayoutEffect(displayInputs, () => [...getInputs(), JSON.stringify(manager.state.value)]);
                onWillDestroy(cleanup);
            } else {
                displayInputs();
            }
            return manager;
        };
        return service;
    },
});
