(function () {
    function getRoomId() {
        const node = document.getElementById('teacher-metrics');
        return node ? node.dataset.room : null;
    }

    function formatNumber(n) {
        return typeof n === 'number' ? n.toLocaleString() : n;
    }

    async function fetchMetrics(roomId) {
        const url = `/api/teacher-metrics/?room=${roomId}`;
        const resp = await fetch(url, { credentials: 'same-origin' });
        if (!resp.ok) throw new Error('Не удалось получить метрики');
        return await resp.json();
    }

    function renderTasksTrend(ctx, data) {
        const labels = data.map(d => d.date.split('T')[0]);
        const values = data.map(d => d.total);
        return new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: 'Расходы по дням',
                    data: values,
                    borderColor: '#2b90d9',
                    backgroundColor: 'rgba(43,144,217,0.08)',
                    tension: 0.2,
                    fill: true,
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true } }
            }
        });
    }

    function renderExpensesCategory(ctx, categories) {
        const labels = categories.map(c => c.category || '(без категории)');
        const values = categories.map(c => parseFloat(c.total || 0));
        return new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels,
                datasets: [{
                    data: values,
                    backgroundColor: ['#4caf50', '#ff9800', '#f44336', '#2196f3', '#9c27b0', '#607d8b'],
                }]
            },
            options: { responsive: true }
        });
    }

    document.addEventListener('DOMContentLoaded', async () => {
        const roomId = getRoomId();
        if (!roomId) return;

        const csvBtn = document.getElementById('download-metrics-csv');
        if (csvBtn) {
            csvBtn.addEventListener('click', () => {
                window.location.href = `/api/teacher-metrics/?room=${roomId}&format=csv`;
            });
        }

        try {
            const metrics = await fetchMetrics(roomId);
            const trendCtx = document.getElementById('chart-tasks-trend').getContext('2d');
            const catCtx = document.getElementById('chart-expenses-category').getContext('2d');

            // Use expenses_trend for line and top_categories for donut
            renderTasksTrend(trendCtx, metrics.expenses_trend || []);
            renderExpensesCategory(catCtx, metrics.top_categories || []);

        } catch (err) {
            console.error('Metrics error', err);
        }
    });
})();
