// financial-charts.js
// Minimal Chart.js wiring to render monthly and yearly charts and update via AJAX

let monthlyJobsChart = null;
let monthlyFinancialChart = null;
let yearlyFinancialChart = null;

function createOrUpdateBarChart(ctx, labels, data, label, backgroundColor) {
    if (ctx._chartInstance) {
        ctx._chartInstance.data.labels = labels;
        ctx._chartInstance.data.datasets[0].data = data;
        ctx._chartInstance.update();
        return ctx._chartInstance;
    }
    const chart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: label,
                data: data,
                backgroundColor: backgroundColor || 'rgba(54, 162, 235, 0.6)'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: true } }
        }
    });
    ctx._chartInstance = chart;
    return chart;
}

function createOrUpdateLineChart(ctx, labels, datasets) {
    if (ctx._chartInstance) {
        ctx._chartInstance.data.labels = labels;
        ctx._chartInstance.data.datasets = datasets;
        ctx._chartInstance.update();
        return ctx._chartInstance;
    }
    const chart = new Chart(ctx, {
        type: 'line',
        data: { labels: labels, datasets: datasets },
        options: { responsive: true, maintainAspectRatio: false }
    });
    ctx._chartInstance = chart;
    return chart;
}

function updateChartsFromPayload(payload) {
    const monthly = payload.monthly || [];
    const yearly = payload.yearly || [];

    const monthLabels = monthly.map(m => m.label);
    const jobsData = monthly.map(m => m.jobs_finished);
    const partsData = monthly.map(m => m.parts_income);
    const serviceData = monthly.map(m => m.service_income);
    const vendorExpense = monthly.map(m => m.vendor_expense);

    const monthlyJobsCtx = document.getElementById('monthlyJobsChart').getContext('2d');
    createOrUpdateBarChart(monthlyJobsCtx, monthLabels, jobsData, 'Jobs Finished', 'rgba(75, 192, 192, 0.6)');

    const monthlyFinancialCtx = document.getElementById('monthlyFinancialChart').getContext('2d');
    const datasets = [
        { label: 'Parts Income', data: partsData, borderColor: 'rgba(54,162,235,0.8)', backgroundColor: 'rgba(54,162,235,0.25)', fill: true },
        { label: 'Service Income', data: serviceData, borderColor: 'rgba(255,159,64,0.8)', backgroundColor: 'rgba(255,159,64,0.25)', fill: true },
        { label: 'Vendor Expense', data: vendorExpense, borderColor: 'rgba(255,99,132,0.8)', backgroundColor: 'rgba(255,99,132,0.25)', fill: true }
    ];
    createOrUpdateLineChart(monthlyFinancialCtx, monthLabels, datasets);

    const yearlyLabels = yearly.map(y => String(y.year));
    const yearlyProfit = yearly.map(y => y.net_profit);
    const yearlyCtx = document.getElementById('yearlyFinancialChart').getContext('2d');
    createOrUpdateBarChart(yearlyCtx, yearlyLabels, yearlyProfit, 'Yearly Net Profit', 'rgba(153,102,255,0.6)');
}

async function fetchAndRenderCharts(queryString) {
    try {
        const url = '/staff/reports/chart-data/' + (queryString || window.location.search);
        const res = await fetch(url, { credentials: 'same-origin' });
        if (!res.ok) throw new Error('Failed to fetch chart data');
        const payload = await res.json();
        updateChartsFromPayload(payload);
    } catch (err) {
        console.error('Error loading charts:', err);
    }
}

// Wire the report filters form to update charts via AJAX (prevent full reload)
document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('reportFiltersForm');
    if (form) {
        // Initial load: fetch charts for current query parameters
        fetchAndRenderCharts('?' + new URLSearchParams(new FormData(form)).toString());

        form.addEventListener('submit', function(e) {
            e.preventDefault();
            const qs = '?' + new URLSearchParams(new FormData(form)).toString();
            // Update the URL shown in the browser without reloading
            if (history && history.pushState) {
                history.pushState(null, '', qs);
            }
            fetchAndRenderCharts(qs);
        });
    }
});
