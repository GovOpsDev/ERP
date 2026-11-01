import { patch } from '@web/core/utils/patch';
import { getCurrency } from '@web/core/currency';
import { computeFormatFromCurrency } from '@spreadsheet/currency/helpers';
import { ChartDataSource } from '@spreadsheet/chart/data_source/chart_data_source';

// Only charts explicitly marked by the project budget dashboard use integers.
// Pivot/list reports, exports, ORM values and other dashboards keep full precision.
function usesWholeAmounts(source) {
    return source._searchParams.context?.erp_budget_integer_display === true &&
        ['erp.budget.report', 'erp.budget.ledger.report'].includes(source._metaData.resModel);
}

patch(ChartDataSource.prototype, {
    _getCurrencyFormatForId(currencyId) {
        if (usesWholeAmounts(this)) {
            const currency = getCurrency(currencyId);
            return currency ? computeFormatFromCurrency({...currency, decimalPlaces: 0}) : '#,##0';
        }
        return super._getCurrencyFormatForId(currencyId);
    },
    getData() {
        const data = super.getData();
        if (!usesWholeAmounts(this)) {
            return data;
        }
        // Work on copies of already aggregated display points; don't mutate the
        // source cache or truncate individual ledger entries before summation.
        return {
            ...data,
            datasets: data.datasets.map(dataset => ({
                ...dataset,
                data: dataset.data.map(point => ({
                    ...point,
                    value: typeof point.value === 'number' && Number.isFinite(point.value)
                        ? Math.trunc(point.value) || 0 : point.value,
                })),
            })),
        };
    },
});
