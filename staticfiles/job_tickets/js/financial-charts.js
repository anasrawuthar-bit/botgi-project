// Function to update all charts with data from payload
function updateChartsFromPayload(payload) {
    // 1. Monthly Jobs Chart
    const monthlyJobsCtx = document.getElementById('monthlyJobsChart').getContext('2d');
    new Chart(monthlyJobsCtx, {
        type: 'bar',
        data: {
            labels: payload.monthly.map(m => m.label),
            datasets: [{
                label: 'Jobs Finished',
                data: payload.monthly.map(m => m.jobs_finished),
                backgroundColor: 'rgba(54, 162, 235, 0.5)',
                borderColor: 'rgba(54, 162, 235, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1
                    }
                }
            }
        }
    });

    // 2. Monthly Income vs Expense Chart
    const monthlyFinancialCtx = document.getElementById('monthlyFinancialChart').getContext('2d');
    new Chart(monthlyFinancialCtx, {
        type: 'bar',
        data: {
            labels: payload.monthly.map(m => m.label),
            datasets: [{
                label: 'Total Income',
                data: payload.monthly.map(m => m.total_income),
                backgroundColor: 'rgba(75, 192, 192, 0.5)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 1
            }, {
                label: 'Vendor Expense',
                data: payload.monthly.map(m => m.vendor_expense),
                backgroundColor: 'rgba(255, 99, 132, 0.5)',
                borderColor: 'rgba(255, 99, 132, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return '₹' + value;
                        }
                    }
                }
            }
        }
    });

    // 3. Yearly Net Profit Chart
    const yearlyFinancialCtx = document.getElementById('yearlyFinancialChart').getContext('2d');
    new Chart(yearlyFinancialCtx, {
        type: 'bar',
        data: {
            labels: payload.yearly.map(y => y.year.toString()),
            datasets: [{
                label: 'Net Profit',
                data: payload.yearly.map(y => y.net_profit),
                backgroundColor: 'rgba(153, 102, 255, 0.5)',
                borderColor: 'rgba(153, 102, 255, 1)',
                borderWidth: 1
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return '₹' + value;
                        }
                    }
                }
            }
        }
    });
}

// For reports_dashboard.html - AJAX version
document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('reportFiltersForm');
    if (form) {
        // This is the reports dashboard page
        function updateCharts() {
            const formData = new FormData(form);
            const searchParams = new URLSearchParams(formData);
            
            fetch('/staff/reports/chart-data/?' + searchParams.toString())
                .then(response => response.json())
                .then(payload => {
                    updateChartsFromPayload(payload);
                })
                .catch(error => console.error('Error fetching chart data:', error));
        }

        // Update charts on page load and form submission
        updateCharts();
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            updateCharts();
        });
    }
});