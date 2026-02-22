// Chart.js initialization and data management

let chartInstance = null;
let projectedAccountBalancesByYear = {};
let actualAccountBalancesByYear = {};
let projectedTotalsByYear = {};
let actualTotalsByYear = {};

if (window.Chart) {
    Chart.defaults.font.family = 'Montserrat, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
    Chart.defaults.color = '#475569';
}

// Color palette for multiple users
const userColors = {
    'Steven': { border: '#1F3A8A', bg: 'rgba(31, 58, 138, 0.12)' },
    'Alyssa': { border: '#C8A44D', bg: 'rgba(200, 164, 77, 0.14)' },
    'User3': { border: '#06B6D4', bg: 'rgba(6, 182, 212, 0.1)' },
    'User4': { border: '#8B5CF6', bg: 'rgba(139, 92, 246, 0.1)' },
};

const stressTierStyles = {
    5: { color: '#166534', bg: '#DCFCE7', border: '#86EFAC' },
    4: { color: '#3F6212', bg: '#ECFCCB', border: '#BEF264' },
    3: { color: '#92400E', bg: '#FEF3C7', border: '#FCD34D' },
    2: { color: '#9A3412', bg: '#FFEDD5', border: '#FDBA74' },
    1: { color: '#991B1B', bg: '#FEE2E2', border: '#FCA5A5' },
};

function createYearTickCallback(cadence = 4) {
    return function(_value, index) {
        const labels = (this && typeof this.getLabels === 'function') ? this.getLabels() : [];
        const lastIndex = labels.length - 1;
        if (index === lastIndex || index === 0 || index % cadence === 0) {
            return labels[index];
        }
        return '';
    };
}

async function loadUserData() {
    const userSelect = document.getElementById('userSelect');
    const selectedValue = userSelect ? userSelect.value : '';
    console.log('loadUserData called - userSelect value:', selectedValue);
    
    if (!selectedValue) {
        console.log('No user selected');
        return;
    }
    
    const addBalanceBtn = document.getElementById('addBalanceBtn');
    const deltaTable = document.getElementById('deltaTable');
    const stressTestSection = document.getElementById('stressTestSection');
    
    // Show/hide balance add button and delta table based on selection
    if (selectedValue === 'all') {
        console.log('Loading all users view');
        addBalanceBtn.style.display = 'none';
        deltaTable.style.display = 'none';
        if (stressTestSection) {
            stressTestSection.style.display = 'none';
        }
        loadAllUsers();
    } else {
        console.log('Loading single user:', selectedValue);
        addBalanceBtn.style.display = 'inline-block';
        deltaTable.style.display = 'block';
        if (stressTestSection) {
            stressTestSection.style.display = 'block';
        }
        loadSingleUser(selectedValue);
    }
}

async function loadSingleUser(username) {
    try {
        console.log('loadSingleUser called for:', username);
        const apiUrl = `/api/comparison/${username}`;
        console.log('Fetching from:', apiUrl);

        // Fetch comparison data and (for Steven) match scenarios in parallel
        const fetchComparison = fetch(apiUrl);
        const fetchScenarios = (username === 'Steven')
            ? fetch(`/api/match-scenarios/${username}`)
            : Promise.resolve(null);

        const [response, scenariosResponse] = await Promise.all([fetchComparison, fetchScenarios]);
        console.log('API response:', response.status, response.statusText);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const data = await response.json();
        console.log('API response received. Data:', data);
        console.log('Projected data points:', data.projected ? data.projected.length : 'none');
        console.log('Deltas from API:', data.deltas);

        let matchScenarios = null;
        if (scenariosResponse && scenariosResponse.ok) {
            matchScenarios = await scenariosResponse.json();
            console.log('Match scenarios loaded:', matchScenarios ? Object.keys(matchScenarios) : 'none');
        }

        renderSingleUserChart(username, data, matchScenarios);
        renderDeltaTable(data.deltas);
        await syncStressTestUiForSelection(username);
    } catch (error) {
        console.error('Error loading user data:', error);
        document.getElementById('deltaContent').innerHTML = 
            `<p class="loading" style="color: #9A3412;">Error loading data: ${error.message}</p>`;
        document.getElementById('retirementChart').innerHTML =
            `<p class="loading" style="color: #9A3412;">Error loading data: ${error.message}</p>`;
    }
}

async function loadAllUsers() {
    try {
        const response = await fetch(`/api/comparison-all`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        renderAllUsersChart(data.users);
    } catch (error) {
        console.error('Error loading all users:', error);
        document.getElementById('retirementChart').innerHTML = 
            `<p class="loading" style="color: #9A3412;">Error loading data: ${error.message}</p>`;
    }
}

function renderSingleUserChart(username, data, matchScenarios = null) {
    const ctx = document.getElementById('retirementChart');
    const retirementYear = Number.isFinite(Number(data.retirement_year)) ? Number(data.retirement_year) : null;
    const isMobileViewport = window.innerWidth <= 768;
    
    // Destroy existing chart if it exists
    if (chartInstance) {
        chartInstance.destroy();
    }
    
    // Debug: log the actual data structure
    console.log('Data.actual:', data.actual);
    if (data.actual.length > 0) {
        console.log('First actual entry:', data.actual[0]);
    }
    
    // Extract years from projected data
    const years = data.projected.map(d => d.year);
    
    // Create actual data array matching projected years (null for missing years)
    const actualByYear = {};
    projectedAccountBalancesByYear = {};
    actualAccountBalancesByYear = {};
    projectedTotalsByYear = {};
    actualTotalsByYear = {};
    
    // Populate projected totals and projected account balances
    data.projected.forEach(d => {
        projectedTotalsByYear[d.year] = d.balance;
        projectedAccountBalancesByYear[d.year] = d.account_balances || {};
    });
    
    // Populate actual totals and actual account balances
    data.actual.forEach(d => {
        actualByYear[d.year] = d.balance;
        actualTotalsByYear[d.year] = d.balance;
        actualAccountBalancesByYear[d.year] = d.account_balances || {};
    });
    
    const projectedData = data.projected.map(d => d.balance);
    const actualData = years.map(year => actualByYear[year] || null);
    const actualAboveData = years.map((year, idx) => {
        const actual = actualData[idx];
        const projected = projectedData[idx];
        if (actual === null || projected === null || projected === undefined) {
            return null;
        }
        return actual >= projected ? actual : null;
    });
    const actualBelowData = years.map((year, idx) => {
        const actual = actualData[idx];
        const projected = projectedData[idx];
        if (actual === null || projected === null || projected === undefined) {
            return null;
        }
        return actual < projected ? actual : null;
    });
    const differencePointColors = years.map((year, idx) => {
        const actual = actualData[idx];
        const projected = projectedData[idx];
        if (actual === null || projected === null || projected === undefined) {
            return 'rgba(0,0,0,0)';
        }
        return actual >= projected ? '#16A34A' : '#DC2626';
    });
    
    const retirementMarkerPlugin = {
        id: 'retirementMarker',
        afterDraw(chart, _args, pluginOptions) {
            const markerYear = pluginOptions?.retirementYear;
            if (!markerYear) {
                return;
            }

            const labels = chart.data.labels || [];
            if (!labels.includes(markerYear)) {
                return;
            }

            const xScale = chart.scales.x;
            const chartArea = chart.chartArea;
            if (!xScale || !chartArea) {
                return;
            }

            const x = xScale.getPixelForValue(markerYear);
            const top = chartArea.top;
            const bottom = chartArea.bottom;
            const ctx2d = chart.ctx;
            const segmentHeight = 8;

            ctx2d.save();
            ctx2d.lineWidth = 3;

            let isBlack = true;
            for (let y = top; y < bottom; y += segmentHeight) {
                ctx2d.strokeStyle = isBlack ? '#0F172A' : '#FFFFFF';
                ctx2d.beginPath();
                ctx2d.moveTo(x, y);
                ctx2d.lineTo(x, Math.min(y + segmentHeight, bottom));
                ctx2d.stroke();
                isBlack = !isBlack;
            }

            ctx2d.strokeStyle = 'rgba(15, 23, 42, 0.35)';
            ctx2d.lineWidth = 1;
            ctx2d.beginPath();
            ctx2d.moveTo(x - 2, top);
            ctx2d.lineTo(x - 2, bottom);
            ctx2d.stroke();

            ctx2d.fillStyle = '#0F172A';
            ctx2d.font = '600 11px Montserrat';
            ctx2d.textAlign = 'center';
            ctx2d.fillText('Retirement', x, top + 14);
            ctx2d.restore();
        }
    };

    // Build match scenario datasets (dotted lines, only when data provided)
    const matchDatasets = [];
    if (matchScenarios) {
        const scenarioConfigs = [
            { key: '3pct', label: '+3% 401k Contribution', color: '#0F766E', order: 2 },
            { key: '5pct', label: '+5% 401k Contribution', color: '#7C3AED', order: 3 },
        ];
        for (const cfg of scenarioConfigs) {
            if (matchScenarios[cfg.key]) {
                const byYear = {};
                matchScenarios[cfg.key].forEach(d => { byYear[d.year] = d.balance; });
                matchDatasets.push({
                    label: cfg.label,
                    data: years.map(y => byYear[y] ?? null),
                    borderColor: cfg.color,
                    backgroundColor: 'transparent',
                    borderWidth: 2,
                    borderDash: [7, 5],
                    fill: false,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 7,
                    pointHoverBackgroundColor: cfg.color,
                    pointHoverBorderColor: '#FFFFFF',
                    pointHoverBorderWidth: 2,
                    spanGaps: true,
                    order: cfg.order,
                });
            }
        }
    }

    chartInstance = new Chart(ctx, {
        type: 'line',
        plugins: [retirementMarkerPlugin],
        data: {
            labels: years,
            datasets: [
                ...matchDatasets,
                {
                    label: `${username} - Projected Balance`,
                    data: projectedData,
                    borderColor: '#1F3A8A',
                    backgroundColor: 'rgba(31, 58, 138, 0.12)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 8,
                    pointHoverBackgroundColor: '#3658B0',
                    pointHoverBorderColor: '#FFFFFF',
                    pointHoverBorderWidth: 2,
                    order: 4,
                },
                {
                    label: `${username} - Actual Balance`,
                    data: actualData,
                    borderColor: '#C8A44D',
                    backgroundColor: 'rgba(200, 164, 77, 0.14)',
                    borderWidth: 3,
                    fill: false,
                    tension: 0.4,
                    pointRadius: isMobileViewport ? 4 : 6,
                    pointHoverRadius: isMobileViewport ? 7 : 10,
                    pointBackgroundColor: differencePointColors,
                    pointBorderColor: '#FFFFFF',
                    pointBorderWidth: 2,
                    pointHoverBackgroundColor: differencePointColors,
                    pointHoverBorderColor: '#FFFFFF',
                    pointHoverBorderWidth: 2,
                    spanGaps: true,
                    order: 5,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                retirementMarker: {
                    retirementYear: retirementYear
                },
                legend: {
                    position: isMobileViewport ? 'bottom' : 'top',
                    labels: {
                        color: '#0F172A',
                        font: { size: isMobileViewport ? 11 : 14, weight: '600' },
                        padding: isMobileViewport ? 10 : 20,
                        boxWidth: isMobileViewport ? 14 : 20,
                        boxHeight: isMobileViewport ? 8 : 12,
                        usePointStyle: true,
                        pointStyle: 'circle',
                        generateLabels: function(chart) {
                            const labels = Chart.defaults.plugins.legend.labels.generateLabels(chart);
                            return labels.map((item) => {
                                if (item.text && item.text.includes('Projected Balance')) {
                                    return {
                                        ...item,
                                        fillStyle: 'rgba(31, 58, 138, 0.35)',
                                        strokeStyle: '#1F3A8A',
                                        lineWidth: 2,
                                        pointStyle: 'circle',
                                    };
                                }
                                if (item.text && item.text.includes('Actual Balance')) {
                                    return {
                                        ...item,
                                        fillStyle: 'rgba(200, 164, 77, 0.9)',
                                        strokeStyle: '#8C6A24',
                                        lineWidth: 2,
                                        pointStyle: 'circle',
                                    };
                                }
                                return item;
                            });
                        },
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 23, 42, 0.96)',
                    titleColor: '#F8FAFC',
                    bodyColor: '#E2E8F0',
                    borderColor: '#334155',
                    borderWidth: 1,
                    padding: isMobileViewport ? 10 : 16,
                    cornerRadius: 12,
                    displayColors: true,
                    usePointStyle: true,
                    boxPadding: 6,
                    titleMarginBottom: 10,
                    bodySpacing: 6,
                    titleFont: { size: isMobileViewport ? 12 : 14, weight: '700' },
                    bodyFont: { size: isMobileViewport ? 11 : 13, weight: '600' },
                    callbacks: {
                        title: function(context) {
                            return 'Year ' + context[0].label;
                        },
                        labelPointStyle: function() {
                            return {
                                pointStyle: 'circle',
                                rotation: 0
                            };
                        },
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += new Intl.NumberFormat('en-US', {
                                    style: 'currency',
                                    currency: 'USD',
                                    minimumFractionDigits: 2,
                                    maximumFractionDigits: 2,
                                }).format(context.parsed.y);
                            }
                            return label;
                        },
                        afterBody: function(context) {
                            if (!context || context.length === 0) {
                                return '';
                            }

                            const year = context[0].label;
                            const projectedBreakdown = projectedAccountBalancesByYear[year] || {};
                            const actualBreakdown = actualAccountBalancesByYear[year] || {};

                            const formatMoney = (value) => new Intl.NumberFormat('en-US', {
                                style: 'currency',
                                currency: 'USD',
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            }).format(value || 0);

                            const rows = [];

                            if (projectedTotalsByYear[year] !== undefined) {
                                rows.push('Projected (Total): ' + formatMoney(projectedTotalsByYear[year]));
                                rows.push('Projected (401k): ' + formatMoney(projectedBreakdown['401k']));
                                rows.push('Projected (IRA): ' + formatMoney(projectedBreakdown['roth_ira']));
                            }

                            if (actualTotalsByYear[year] !== undefined) {
                                rows.push('Actual (Total): ' + formatMoney(actualTotalsByYear[year]));
                                rows.push('Actual (401k): ' + formatMoney(actualBreakdown['401k']));
                                rows.push('Actual (IRA): ' + formatMoney(actualBreakdown['roth_ira']));
                            }

                            return rows;
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'Year',
                        color: '#B3B3B3',
                        font: { size: 13, weight: '600' }
                    },
                    grid: { 
                        color: 'rgba(45, 45, 45, 0.5)',
                        drawBorder: false
                    },
                    ticks: {
                        color: '#6B6B6B',
                        font: { size: isMobileViewport ? 10 : 12 },
                        autoSkip: false,
                        callback: createYearTickCallback(4)
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Balance ($)',
                        color: '#B3B3B3',
                        font: { size: 13, weight: '600' }
                    },
                    ticks: {
                        color: '#6B6B6B',
                        font: { size: isMobileViewport ? 10 : 12 },
                        callback: function(value) {
                            return new Intl.NumberFormat('en-US', {
                                style: 'currency',
                                currency: 'USD',
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            }).format(value);
                        }
                    },
                    grid: { 
                        color: 'rgba(45, 45, 45, 0.5)',
                        drawBorder: false
                    }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index',
            }
        }
    });
}

function renderAllUsersChart(usersData) {
    const ctx = document.getElementById('retirementChart');
    const isMobileViewport = window.innerWidth <= 768;
    
    // Destroy existing chart if it exists
    if (chartInstance) {
        chartInstance.destroy();
    }
    
    if (!usersData || usersData.length === 0) {
        document.getElementById('retirementChart').innerHTML = '<p class="loading">No users found</p>';
        return;
    }
    
    // Get all unique years across all users
    const allYears = new Set();
    let minYear = Infinity;
    let maxYear = -Infinity;
    
    usersData.forEach(user => {
        user.projected.forEach(d => {
            allYears.add(d.year);
            minYear = Math.min(minYear, d.year);
            maxYear = Math.max(maxYear, d.year);
        });
    });
    
    // Create complete year range from min to max
    const years = [];
    for (let year = minYear; year <= maxYear; year++) {
        years.push(year);
    }
    
    console.log('All users comparison - Year range:', minYear, 'to', maxYear, ', Total years:', years.length);
    console.log('Users data received:', usersData.map(u => ({ username: u.username, dataPoints: u.projected.length })));
    
    // Create dataset for each user
    const datasets = usersData.map((user, index) => {
        const colors = userColors[user.username] || {
            border: `hsl(${(index * 60) % 360}, 70%, 50%)`,
            bg: `hsla(${(index * 60) % 360}, 70%, 50%, 0.1)`
        };
        
        const userBalances = {};
        user.projected.forEach(d => {
            userBalances[d.year] = d.balance;
        });
        
        const dataArray = years.map(year => userBalances[year] !== undefined ? userBalances[year] : null);
        console.log(`${user.username} - Data array length: ${dataArray.length}, Years covered: ${user.projected.length}, Data points:`, {
            firstYear: user.projected[0]?.year,
            lastYear: user.projected[user.projected.length - 1]?.year,
            firstDataValue: dataArray[0],
            lastDataValue: dataArray[dataArray.length - 1],
            nullCount: dataArray.filter(v => v === null).length
        });
        
        return {
            label: `${user.username} - Projected`,
            data: dataArray,
            borderColor: colors.border,
            backgroundColor: colors.bg,
            borderWidth: 2.5,
            fill: false,
            tension: 0.1,
            pointRadius: 4,
            pointHoverRadius: 6,
            spanGaps: true,
        };
    });
    
    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: years,
            datasets: datasets,
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: isMobileViewport ? 'bottom' : 'top',
                    labels: {
                        color: '#0F172A',
                        font: { size: isMobileViewport ? 11 : 14, weight: '600' },
                        padding: isMobileViewport ? 10 : 20,
                        usePointStyle: true,
                        pointStyle: 'circle',
                    },
                    generateLabels: function(chart) {
                        return chart.data.datasets
                            .map((dataset, index) => {
                                if (!dataset.label || dataset.label.trim() === '') {
                                    return null;
                                }
                                return {
                                    text: dataset.label,
                                    fillStyle: dataset.borderColor || dataset.backgroundColor,
                                    hidden: !chart.isDatasetVisible(index),
                                    index: index,
                                    pointStyle: 'circle',
                                };
                            })
                            .filter(item => item !== null);
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 23, 42, 0.96)',
                    titleColor: '#F8FAFC',
                    bodyColor: '#E2E8F0',
                    borderColor: '#334155',
                    borderWidth: 1,
                    padding: 16,
                    cornerRadius: 12,
                    displayColors: true,
                    usePointStyle: true,
                    boxPadding: 6,
                    titleMarginBottom: 10,
                    bodySpacing: 6,
                    titleFont: { size: 14, weight: '700' },
                    bodyFont: { size: 13, weight: '600' },
                    callbacks: {
                        labelPointStyle: function() {
                            return {
                                pointStyle: 'circle',
                                rotation: 0
                            };
                        },
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += new Intl.NumberFormat('en-US', {
                                    style: 'currency',
                                    currency: 'USD',
                                    minimumFractionDigits: 2,
                                    maximumFractionDigits: 2,
                                }).format(context.parsed.y);
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'Year',
                        color: '#475569',
                        font: { size: 13, weight: '600' }
                    },
                    grid: { 
                        color: 'rgba(226, 232, 240, 0.8)',
                        drawBorder: false
                    },
                    ticks: {
                        color: '#64748B',
                        font: { size: 12 },
                        autoSkip: false,
                        callback: createYearTickCallback(4)
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Balance ($)',
                        color: '#475569',
                        font: { size: 13, weight: '600' }
                    },
                    ticks: {
                        color: '#64748B',
                        font: { size: 12 },
                        callback: function(value) {
                            return new Intl.NumberFormat('en-US', {
                                style: 'currency',
                                currency: 'USD',
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            }).format(value);
                        }
                    },
                    grid: { 
                        color: 'rgba(226, 232, 240, 0.8)',
                        drawBorder: false
                    }
                }
            },
            interaction: {
                intersect: false,
                mode: 'index',
            }
        }
    });
}

function renderDeltaTable(deltas) {
    const content = document.getElementById('deltaContent');
    
    if (!deltas || deltas.length === 0) {
        content.innerHTML = '<p class="loading">No actual balance data entered yet. Add balances to see comparison.</p>';
        return;
    }
    
    console.log('renderDeltaTable - deltas received:', deltas);
    
    let html = '<table><thead><tr>';
    html += '<th>Year</th>';
    html += '<th>Projected</th>';
    html += '<th>Actual</th>';
    html += '<th>Difference ($)</th>';
    html += '<th>Difference (%)</th>';
    html += '<th>Last Updated</th>';
    html += '<th>Actions</th>';
    html += '</tr></thead><tbody>';
    
    deltas.forEach((delta, idx) => {
        const diffClass = delta.delta >= 0 ? 'positive' : 'negative';
        const diffSign = delta.delta >= 0 ? '+' : '';
        const balanceIdStr = delta.balance_ids ? delta.balance_ids.join(',') : '';
        
        // Format timestamp to EST timezone
        let timestampDisplay = '-';
        if (delta.timestamp) {
            try {
                // Parse as UTC by appending Z if not present
                let isoString = delta.timestamp;
                if (!isoString.includes('Z') && !isoString.includes('+') && !isoString.includes('-', 10)) {
                    isoString += 'Z';
                }
                const date = new Date(isoString);
                timestampDisplay = date.toLocaleString('en-US', {
                    timeZone: 'America/New_York',
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: true
                });
            } catch (e) {
                timestampDisplay = delta.timestamp;
            }
        }
        
        console.log(`Delta ${idx} - year: ${delta.year}, balance_ids:`, delta.balance_ids, 'balanceIdStr:', balanceIdStr);
        
        html += '<tr>';
        html += `<td><strong>${delta.year}</strong></td>`;
        html += `<td>${formatCurrency(delta.projected)}</td>`;
        html += `<td>${formatCurrency(delta.actual)}</td>`;
        html += `<td class="${diffClass}">${diffSign}${formatCurrency(delta.delta)}</td>`;
        html += `<td class="${diffClass}">${diffSign}${delta.delta_pct.toFixed(2)}%</td>`;
        html += `<td>${timestampDisplay}</td>`;
        html += `<td class="action-buttons">
                    <button type="button" class="btn-edit" data-balance-ids="${balanceIdStr}" data-year="${delta.year}" data-balance="${delta.actual}" title="Edit">✏️</button>
                    <button type="button" class="btn-delete" onclick="handleDeleteClick('${balanceIdStr}', ${delta.year})" title="Delete">🗑️</button>
                </td>`;
        html += '</tr>';
    });
    
    html += '</tbody></table>';
    content.innerHTML = html;
    
    // Attach event listeners to edit buttons (different elements)
    const editButtons = content.querySelectorAll('.btn-edit');
    console.log(`Found ${editButtons.length} edit buttons`);
    
    editButtons.forEach((btn, idx) => {
        console.log(`Attaching edit listener to button ${idx}`);
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const balanceIdStr = this.getAttribute('data-balance-ids');
            const year = parseInt(this.getAttribute('data-year'));
            const balance = parseFloat(this.getAttribute('data-balance'));
            console.log(`Edit button ${idx} clicked - year: ${year}, balanceIdStr: ${balanceIdStr}`);
            editBalance(balanceIdStr, year, balance);
        });
    });
}

function handleDeleteClick(balanceIdStr, year) {
    console.log(`handleDeleteClick called - balanceIdStr: ${balanceIdStr}, year: ${year}`);
    deleteBalance(balanceIdStr, year);
}

function formatCurrency(value) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(value);
}

function formatTimestamp(timestamp) {
    if (!timestamp) {
        return '-';
    }

    try {
        let isoString = timestamp;
        if (!isoString.includes('Z') && !isoString.includes('+') && !isoString.includes('-', 10)) {
            isoString += 'Z';
        }
        const date = new Date(isoString);
        return date.toLocaleString('en-US', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            hour12: true,
        });
    } catch (error) {
        return timestamp;
    }
}

async function loadStressTestResult(username) {
    const stressContent = document.getElementById('stressTestContent');
    if (!stressContent || !username || username === 'all') {
        return;
    }

    stressContent.innerHTML = '<p class="loading">Loading latest stress test...</p>';

    try {
        const response = await fetch(`/api/stress-test/${username}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const payload = await response.json();
        renderStressTestResult(payload.result);
    } catch (error) {
        stressContent.innerHTML = `<p class="loading" style="color: #F97316;">Unable to load stress test: ${error.message}</p>`;
    }
}

function renderStressTestResult(result) {
    const stressContent = document.getElementById('stressTestContent');
    if (!stressContent) {
        return;
    }

    if (!result) {
        stressContent.innerHTML = `
            <div class="stress-empty">
                <p>No stress test is stored yet for this user.</p>
                <p>Run <strong>Recalculate Stress Test</strong> to generate a persistent Monte Carlo result.</p>
            </div>
        `;
        return;
    }

    const probability = Number(result.success_probability_pct || 0);
    const markerLeft = Math.max(0, Math.min(100, probability));
    const tier = Number(result.rating_tier || 1);
    const tierStyle = stressTierStyles[tier] || stressTierStyles[1];
    const explanation = result.assumptions?.success_definition
        ? 'Success = portfolio avoids depletion before life expectancy and stays above minimum real threshold.'
        : 'Monte Carlo estimate based on current assumptions.';

    const isJoint = result.assumptions && result.assumptions.joint === true;
    const memberRows = isJoint && result.assumptions.members
        ? result.assumptions.members.map(m => `
            <tr>
                <td><strong>${m.name}</strong></td>
                <td>${m.age}</td>
                <td>${m.retirement_age}</td>
                <td>${formatCurrency(m.starting_401k)}</td>
                <td>${formatCurrency(m.starting_ira)}</td>
                <td>${formatCurrency(m.starting_401k + m.starting_ira)}</td>
                <td>${(m.contribution_pct * 100).toFixed(1)}%</td>
                <td>${(m.company_match_pct * 100).toFixed(1)}%</td>
                <td>${formatCurrency(m.annual_salary)}</td>
                <td>${(m.salary_growth_pct * 100).toFixed(1)}%</td>
            </tr>`).join('')
        : '';

    const horizon = result.assumptions?.horizon || {};
    const portfolio = result.assumptions?.portfolio_snapshot || result.assumptions?.household_portfolio_snapshot || {};
    const cashflow = result.assumptions?.cashflow || {};
    const model = result.assumptions?.model || {};
    const successDef = result.assumptions?.success_definition || {};
    const debtPaydown = result.assumptions?.debt_paydown || {};
    const debtItem = debtPaydown.debts && debtPaydown.debts.length > 0 ? debtPaydown.debts[0] : null;
    const outcomes = result.assumptions?.outcome_percentiles || {};
    const retirementOutcomes = outcomes.retirement || null;
    const lifeOutcomes = outcomes.life || null;

    const retirementP10 = retirementOutcomes ? retirementOutcomes.p10 : result.p10_terminal_balance;
    const retirementP50 = retirementOutcomes ? retirementOutcomes.p50 : result.p50_terminal_balance;
    const retirementP90 = retirementOutcomes ? retirementOutcomes.p90 : result.p90_terminal_balance;
    const lifeP10 = lifeOutcomes ? lifeOutcomes.p10 : result.p10_terminal_balance;
    const lifeP50 = lifeOutcomes ? lifeOutcomes.p50 : result.p50_terminal_balance;
    const lifeP90 = lifeOutcomes ? lifeOutcomes.p90 : result.p90_terminal_balance;

    const assumptionsHtml = `
        <div class="assumptions-section">
            <button class="assumptions-toggle" onclick="toggleAssumptions(this)" aria-expanded="false">
                <span class="toggle-arrow">▸</span> Details &amp; Assumptions
            </button>
            <div class="assumptions-panel" style="display:none;">

                ${isJoint ? `
                <div class="assumptions-group">
                    <div class="assumptions-group-title">Household Members</div>
                    <div class="assumptions-table-wrap">
                        <table class="assumptions-table">
                            <thead><tr>
                                <th>Name</th><th>Age</th><th>Retire At</th>
                                <th>401k Start</th><th>IRA Start</th><th>Total</th>
                                <th>Contrib%</th><th>Match%</th><th>Salary</th><th>Salary Growth</th>
                            </tr></thead>
                            <tbody>${memberRows}</tbody>
                        </table>
                    </div>
                </div>` : ''}

                <div class="assumptions-grid">
                    <div class="assumptions-group">
                        <div class="assumptions-group-title">Timeline</div>
                        ${horizon.current_age !== undefined ? `<div class="assump-row"><span>Current Age</span><span>${horizon.current_age}</span></div>` : ''}
                        ${horizon.retirement_age !== undefined ? `<div class="assump-row"><span>Retirement Age</span><span>${horizon.retirement_age}</span></div>` : ''}
                        <div class="assump-row"><span>Life Expectancy</span><span>${horizon.life_expectancy_age || 95}</span></div>
                        <div class="assump-row"><span>Years Simulated</span><span>${horizon.years_simulated || '—'}</span></div>
                    </div>

                    <div class="assumptions-group">
                        <div class="assumptions-group-title">Portfolio Snapshot</div>
                        ${portfolio.starting_total_balance !== undefined ? `<div class="assump-row"><span>Starting Balance</span><span>${formatCurrency(portfolio.starting_total_balance)}</span></div>` : ''}
                        ${portfolio.combined_starting_balance !== undefined ? `<div class="assump-row"><span>Combined Balance</span><span>${formatCurrency(portfolio.combined_starting_balance)}</span></div>` : ''}
                        <div class="assump-row"><span>Blended Return</span><span>${Number(portfolio.blended_expected_return_pct || 0).toFixed(2)}%</span></div>
                        <div class="assump-row"><span>Blended Volatility</span><span>${Number(portfolio.blended_volatility_pct || 0).toFixed(2)}%</span></div>
                    </div>

                    <div class="assumptions-group">
                        <div class="assumptions-group-title">Cashflow Rules</div>
                        <div class="assump-row"><span>Withdrawal Rate</span><span>${((cashflow.withdrawal_rate || 0.04) * 100).toFixed(1)}%</span></div>
                        <div class="assump-row"><span>Inflation Rate</span><span>${((cashflow.inflation_rate || 0.025) * 100).toFixed(1)}%</span></div>
                        <div class="assump-row"><span>Withdrawal Schedule</span><span class="assump-note">${cashflow.withdrawal_phase || 'Begins at retirement, grows with inflation'}</span></div>
                    </div>

                    <div class="assumptions-group">
                        <div class="assumptions-group-title">Debt Paydown</div>
                        <div class="assump-row"><span>Enabled</span><span>${debtPaydown.enabled ? 'Yes' : 'No'}</span></div>
                        ${debtItem ? `<div class="assump-row"><span>Debt</span><span>${debtItem.name || 'Student Loans'}</span></div>` : ''}
                        ${debtItem ? `<div class="assump-row"><span>Principal</span><span>${formatCurrency(debtItem.principal || 0)}</span></div>` : ''}
                        ${debtItem ? `<div class="assump-row"><span>Interest Rate</span><span>${((debtItem.annual_interest_rate || 0) * 100).toFixed(2)}%</span></div>` : ''}
                        ${debtItem ? `<div class="assump-row"><span>Base Monthly</span><span>${formatCurrency(debtItem.base_monthly_payment || 0)}</span></div>` : ''}
                        ${debtItem ? `<div class="assump-row"><span>Extra Monthly</span><span>${formatCurrency(debtItem.additional_monthly_payment_min || 0)} - ${formatCurrency(debtItem.additional_monthly_payment_max || 0)}</span></div>` : ''}
                        <div class="assump-row"><span>Post-Payoff Step</span><span>${debtPaydown.policy?.post_payoff_contribution_step_pct || 1}% / year</span></div>
                        <div class="assump-row"><span>Contribution Cap</span><span>${debtPaydown.policy?.post_payoff_contribution_cap_pct || 15}%</span></div>
                    </div>

                    <div class="assumptions-group">
                        <div class="assumptions-group-title">Success Definition</div>
                        <div class="assump-row"><span>No Depletion</span><span>${successDef.no_depletion_before_life_expectancy ? 'Yes' : 'No'}</span></div>
                        <div class="assump-row"><span>Min Real Terminal</span><span>${successDef.min_real_terminal_threshold_pct_of_retirement_balance || 10}% of retirement balance</span></div>
                    </div>

                    <div class="assumptions-group">
                        <div class="assumptions-group-title">Return Model</div>
                        <div class="assump-row"><span>Distribution</span><span class="assump-note">Lognormal w/ Student-t shocks (df=7)</span></div>
                        <div class="assump-row"><span>Downside Skew</span><span>${model.downside_skew_multiplier || 1.15}× amplification</span></div>
                        <div class="assump-row"><span>Volatility Clustering</span><span class="assump-note">GARCH-like (ω=0.08, α=0.17, β=0.78)</span></div>
                        <div class="assump-row"><span>Simulations</span><span>${(result.simulation_count || 10000).toLocaleString()}</span></div>
                    </div>

                    <div class="assumptions-group">
                        <div class="assumptions-group-title">Retirement Outcome Percentiles</div>
                        <div class="assump-row"><span>P10 (Pessimistic)</span><span>${formatCurrency(retirementP10)}</span></div>
                        <div class="assump-row"><span>P50 (Median)</span><span>${formatCurrency(retirementP50)}</span></div>
                        <div class="assump-row"><span>P90 (Optimistic)</span><span>${formatCurrency(retirementP90)}</span></div>
                    </div>

                    <div class="assumptions-group">
                        <div class="assumptions-group-title">Life Outcome Percentiles</div>
                        <div class="assump-row"><span>P10 (Pessimistic)</span><span>${formatCurrency(lifeP10)}</span></div>
                        <div class="assump-row"><span>P50 (Median)</span><span>${formatCurrency(lifeP50)}</span></div>
                        <div class="assump-row"><span>P90 (Optimistic)</span><span>${formatCurrency(lifeP90)}</span></div>
                    </div>
                </div>
            </div>
        </div>
    `;

    stressContent.innerHTML = `
        <div class="stress-card">
            <div class="stress-card-top">
                <div class="stress-score">
                    <span class="stress-score-percent" style="color: ${tierStyle.color};">${probability.toFixed(1)}%</span>
                    <span class="stress-rating-chip" style="color: ${tierStyle.color}; background: ${tierStyle.bg}; border-color: ${tierStyle.border};">
                        ${result.rating_grade} · ${result.rating_label}
                    </span>
                    <span class="stress-help" title="${explanation}">ⓘ</span>
                </div>
                ${isJoint ? '<span class="joint-badge">Household</span>' : ''}
            </div>

            <div class="stress-gauge" aria-label="Probability of successful retirement gauge">
                <div class="stress-gauge-track">
                    <div class="stress-gauge-marker" style="left: ${markerLeft}%;"></div>
                </div>
                <div class="stress-ticks">
                    <span class="tick-edge-left" style="left: 0%;">0%</span>
                    <span style="left: 60%;">60%</span>
                    <span style="left: 75%;">75%</span>
                    <span style="left: 85%;">85%</span>
                    <span style="left: 92%;">92%</span>
                    <span class="tick-edge-right" style="left: 100%;">100%</span>
                </div>
            </div>

            <div class="stress-meta">
                <div class="stress-meta-item">
                    <span class="stress-meta-label">Simulations</span>
                    <span class="stress-meta-value">${result.simulation_count.toLocaleString()}</span>
                </div>
                <div class="stress-meta-item">
                    <span class="stress-meta-label">Expected Return</span>
                    <span class="stress-meta-value">${Number(result.mean_return_pct).toFixed(2)}%</span>
                </div>
                <div class="stress-meta-item">
                    <span class="stress-meta-label">Volatility</span>
                    <span class="stress-meta-value">${Number(result.volatility_pct).toFixed(2)}%</span>
                </div>
                <div class="stress-meta-item">
                    <span class="stress-meta-label">Inflation</span>
                    <span class="stress-meta-value">${Number(result.inflation_pct).toFixed(2)}%</span>
                </div>
                <div class="stress-meta-item">
                    <span class="stress-meta-label">Retirement P50</span>
                    <span class="stress-meta-value">${formatCurrency(retirementP50)}</span>
                </div>
                <div class="stress-meta-item">
                    <span class="stress-meta-label">Life P50</span>
                    <span class="stress-meta-value">${formatCurrency(lifeP50)}</span>
                </div>
                <div class="stress-meta-item">
                    <span class="stress-meta-label">Last Calculated</span>
                    <span class="stress-meta-value">${formatTimestamp(result.created_at)}</span>
                </div>
            </div>

            ${assumptionsHtml}
        </div>
    `;
}

function toggleAssumptions(btn) {
    const panel = btn.nextElementSibling;
    const arrow = btn.querySelector('.toggle-arrow');
    const expanded = btn.getAttribute('aria-expanded') === 'true';
    if (expanded) {
        panel.style.display = 'none';
        btn.setAttribute('aria-expanded', 'false');
        if (arrow) arrow.textContent = '▸';
    } else {
        panel.style.display = 'block';
        btn.setAttribute('aria-expanded', 'true');
        if (arrow) arrow.textContent = '▾';
    }
}

// ---------------------------------------------------------------------------
// Joint (household) stress test
// ---------------------------------------------------------------------------

const JOINT_USERNAMES = ['Steven', 'Alyssa'];
let currentStressMode = 'individual'; // 'individual' | 'joint'

function isJointSelection(username) {
    return Boolean(username && username !== 'all' && (username.includes('+') || username.includes(',')));
}

async function syncStressTestUiForSelection(username) {
    const tabIndividual = document.getElementById('stressTabIndividual');
    const tabJoint = document.getElementById('stressTabJoint');
    const recalcStressBtn = document.getElementById('recalculateStressBtn');
    const recalcJointBtn = document.getElementById('recalculateJointBtn');

    if (!tabIndividual || !tabJoint || !recalcStressBtn || !recalcJointBtn) {
        return;
    }

    if (isJointSelection(username)) {
        tabIndividual.style.display = 'none';
        tabJoint.style.display = 'inline-flex';
        currentStressMode = 'joint';
        tabIndividual.classList.remove('active');
        tabJoint.classList.add('active');
        recalcStressBtn.style.display = 'none';
        recalcJointBtn.style.display = 'inline-flex';
        await loadJointStressTestResult();
        return;
    }

    tabIndividual.style.display = 'inline-flex';
    tabJoint.style.display = 'inline-flex';

    if (currentStressMode !== 'individual') {
        toggleStressMode('individual');
        return;
    }

    tabIndividual.classList.add('active');
    tabJoint.classList.remove('active');
    recalcStressBtn.style.display = 'inline-flex';
    recalcJointBtn.style.display = 'none';
    await loadStressTestResult(username);
}

function toggleStressMode(mode) {
    const userSelect = document.getElementById('userSelect');
    const username = userSelect ? userSelect.value : '';

    if (isJointSelection(username) && mode === 'individual') {
        mode = 'joint';
    }

    if (mode === currentStressMode) return;
    currentStressMode = mode;

    document.getElementById('stressTabIndividual').classList.toggle('active', mode === 'individual');
    document.getElementById('stressTabJoint').classList.toggle('active', mode === 'joint');

    if (mode === 'individual') {
        if (username && username !== 'all') {
            loadStressTestResult(username);
        }
        document.getElementById('recalculateStressBtn').style.display = 'inline-flex';
        document.getElementById('recalculateJointBtn').style.display = 'none';
    } else {
        loadJointStressTestResult();
        document.getElementById('recalculateStressBtn').style.display = 'none';
        document.getElementById('recalculateJointBtn').style.display = 'inline-flex';
    }
}

async function loadJointStressTestResult() {
    const stressContent = document.getElementById('stressTestContent');
    if (!stressContent) return;

    stressContent.innerHTML = '<p class="loading">Loading household stress test...</p>';

    try {
        const params = JOINT_USERNAMES.map(u => `usernames=${encodeURIComponent(u)}`).join('&');
        const response = await fetch(`/api/stress-test/joint-result?${params}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        const payload = await response.json();
        renderStressTestResult(payload.result);
        if (!payload.result) {
            document.getElementById('stressTestContent').innerHTML += `
                <div class="stress-empty" style="margin-top:0.75rem;">
                    <p>No household stress test stored yet.</p>
                    <p>Click <strong>Recalculate Household</strong> to run a joint simulation combining both portfolios.</p>
                </div>`;
        }
    } catch (error) {
        stressContent.innerHTML = `<p class="loading" style="color: #F97316;">Unable to load household stress test: ${error.message}</p>`;
    }
}

async function recalculateJointStressTest() {
    const button = document.getElementById('recalculateJointBtn');
    const stressContent = document.getElementById('stressTestContent');
    const originalText = button ? button.textContent : 'Recalculate Household';

    if (button) { button.disabled = true; button.textContent = 'Running…'; }
    if (stressContent) stressContent.innerHTML = '<p class="loading">Running 10,000 household Monte Carlo simulations…</p>';

    try {
        const response = await fetch('/api/stress-test/recalculate-joint', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ usernames: JOINT_USERNAMES, simulation_count: 10000 }),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        const payload = await response.json();
        renderStressTestResult(payload.result);
    } catch (error) {
        if (stressContent) stressContent.innerHTML = `<p class="loading" style="color: #F97316;">Household stress test failed: ${error.message}</p>`;
    } finally {
        if (button) { button.disabled = false; button.textContent = originalText; }
    }
}
async function recalculateStressTest() {
    const userSelect = document.getElementById('userSelect');
    const username = userSelect ? userSelect.value : '';

    if (!username || username === 'all') {
        alert('Please select a single user before running the stress test.');
        return;
    }

    if (isJointSelection(username)) {
        alert('For household selection, use Recalculate Household.');
        return;
    }

    const button = document.getElementById('recalculateStressBtn');
    const stressContent = document.getElementById('stressTestContent');
    const originalButtonText = button ? button.textContent : 'Recalculate Stress Test';

    if (button) {
        button.disabled = true;
        button.textContent = 'Running Stress Test...';
    }
    if (stressContent) {
        stressContent.innerHTML = '<p class="loading">Running 10,000 Monte Carlo simulations. This may take a few seconds...</p>';
    }

    try {
        const response = await fetch(`/api/stress-test/${username}/recalculate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ simulation_count: 10000 }),
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const payload = await response.json();
        renderStressTestResult(payload.result);
    } catch (error) {
        if (stressContent) {
            stressContent.innerHTML = `<p class="loading" style="color: #F97316;">Stress test failed: ${error.message}</p>`;
        }
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = originalButtonText;
        }
    }
}

// Balance form functions
function showBalanceForm() {
    // Populate year dropdown if not already populated
    const yearSelect = document.getElementById('year');
    if (yearSelect.children.length <= 1) {
        const currentYear = 2026;
        const endYear = 2090;
        for (let year = currentYear; year <= endYear; year++) {
            const option = document.createElement('option');
            option.value = year;
            option.textContent = year;
            if (year === currentYear) {
                option.selected = true;
            }
            yearSelect.appendChild(option);
        }
    }
    
    document.getElementById('balanceModal').style.display = 'flex';
}

function hideBalanceForm() {
    document.getElementById('balanceModal').style.display = 'none';
    document.getElementById('balanceForm').reset();
}

async function submitBalance(event) {
    event.preventDefault();
    
    const username = document.getElementById('userSelect').value;
    const year = parseInt(document.getElementById('year').value);
    const balance401k = parseFloat(document.getElementById('balance401k').value || 0);
    const balanceIRA = parseFloat(document.getElementById('balanceIRA').value || 0);
    const notes = document.getElementById('notes').value;
    
    if (balance401k === 0 && balanceIRA === 0) {
        alert('Please enter at least one balance value');
        return;
    }
    
    try {
        // Submit 401k balance if provided
        if (balance401k > 0) {
            console.log(`Submitting 401k balance: ${balance401k} for year ${year}`);
            const response401k = await fetch(`/api/balances/${username}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    account_type: '401k',
                    year: year,
                    balance: balance401k,
                    notes: notes || null,
                }),
            });
            
            if (response401k.status === 409) {
                alert('A 401k balance for this year already exists. Please edit the existing entry.');
                return;
            }
            
            if (!response401k.ok) {
                throw new Error(`401k: HTTP ${response401k.status}: ${response401k.statusText}`);
            }
        }
        
        // Submit IRA balance if provided
        if (balanceIRA > 0) {
            console.log(`Submitting IRA balance: ${balanceIRA} for year ${year}`);
            const responseIRA = await fetch(`/api/balances/${username}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    account_type: 'roth_ira',
                    year: year,
                    balance: balanceIRA,
                    notes: notes || null,
                }),
            });
            
            if (responseIRA.status === 409) {
                alert('A Roth IRA balance for this year already exists. Please edit the existing entry.');
                return;
            }
            
            if (!responseIRA.ok) {
                throw new Error(`IRA: HTTP ${responseIRA.status}: ${responseIRA.statusText}`);
            }
        }
        
        hideBalanceForm();
        loadUserData(); // Refresh chart and table
        alert('Balance(s) added successfully!');
    } catch (error) {
        console.error('Error submitting balance:', error);
        alert(`Error: ${error.message}`);
    }
}

// Edit balance functions
async function editBalance(balanceIdStr, year, currentBalance) {
    console.log(`editBalance called - year: ${year}, currentBalance: ${currentBalance}, balanceIdStr: ${balanceIdStr}`);
    
    const balanceIds = balanceIdStr ? balanceIdStr.split(',').map(id => parseInt(id)) : [];
    
    if (balanceIds.length === 0) {
        alert('Error: No balance ID found');
        return;
    }
    
    // Store the balance IDs for use in submit
    const modal = document.getElementById('editBalanceModal');
    modal.dataset.balanceIds = balanceIdStr;
    modal.dataset.balanceYear = year;
    
    document.getElementById('editYear').value = year;
    document.getElementById('editNotes').value = '';
    
    // Fetch individual balance records
    try {
        const container = document.getElementById('balanceFieldsContainer');
        container.innerHTML = '<p class="loading">Loading balance details...</p>';
        
        const balanceRecords = [];
        for (const balanceId of balanceIds) {
            console.log(`Fetching balance record ${balanceId}`);
            const response = await fetch(`/api/balances/record/${balanceId}`);
            if (!response.ok) {
                throw new Error(`Failed to fetch balance ${balanceId}`);
            }
            const record = await response.json();
            balanceRecords.push(record);
            console.log(`Got balance record:`, record);
        }
        
        // Build form fields dynamically based on fetched records
        let html = '';
        balanceRecords.forEach((record, idx) => {
            const fieldId = `editBalance${idx}`;
            const accountLabel = record.account_type === '401k' ? '401k' : 'Roth IRA';
            html += `
                <div class="form-group">
                    <label for="${fieldId}">${accountLabel} Balance ($):</label>
                    <input type="number" id="${fieldId}" class="balance-field" min="0" step="0.01" 
                           value="${record.balance}" data-balance-id="${record.id}" required>
                </div>
            `;
        });
        
        container.innerHTML = html;
        modal.style.display = 'flex';
    } catch (error) {
        console.error('Error fetching balance records:', error);
        alert(`Error: ${error.message}`);
    }
}

function hideEditBalanceForm() {
    document.getElementById('editBalanceModal').style.display = 'none';
    document.getElementById('editBalanceForm').reset();
}

async function submitEditBalance(event) {
    event.preventDefault();
    
    const modal = document.getElementById('editBalanceModal');
    const balanceIdStr = modal.dataset.balanceIds;
    const balanceIds = balanceIdStr ? balanceIdStr.split(',').map(id => parseInt(id)) : [];
    
    console.log('submitEditBalance - balanceIdStr:', balanceIdStr, 'parsed IDs:', balanceIds);
    
    if (balanceIds.length === 0) {
        alert('Error: No balance IDs found');
        return;
    }
    
    const notes = document.getElementById('editNotes').value;
    
    try {
        // Update each balance record with its new value
        const balanceFields = document.querySelectorAll('.balance-field');
        
        for (let i = 0; i < balanceFields.length; i++) {
            const field = balanceFields[i];
            const balanceId = parseInt(field.getAttribute('data-balance-id'));
            const newBalance = parseFloat(field.value);
            
            console.log(`Submitting edit - balanceId: ${balanceId}, newBalance: ${newBalance}`);
            
            const response = await fetch(`/api/balances/${balanceId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    balance: newBalance,
                    notes: notes,
                }),
            });
            
            console.log(`PUT /api/balances/${balanceId} response: ${response.status}`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
        }
        
        hideEditBalanceForm();
        loadUserData(); // Refresh chart and table
        alert('Balance updated successfully!');
    } catch (error) {
        console.error('Error updating balance:', error);
        alert(`Error: ${error.message}`);
    }
}

async function deleteBalance(balanceIdStr, year) {
    console.log('deleteBalance called - balanceIdStr:', balanceIdStr, 'year:', year);
    
    const balanceIds = balanceIdStr ? balanceIdStr.split(',').map(id => parseInt(id)) : [];
    
    console.log('Parsed balance IDs:', balanceIds);
    
    if (balanceIds.length === 0) {
        alert('Error: No balance ID found');
        return;
    }
    
    try {
        // Delete all balance IDs for this year (both 401k and IRA if applicable)
        for (const balanceId of balanceIds) {
            console.log(`Deleting balance ID: ${balanceId}`);
            const response = await fetch(`/api/balances/${balanceId}`, {
                method: 'DELETE',
            });
            
            console.log(`DELETE /api/balances/${balanceId} response: ${response.status}`);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
        }
        
        loadUserData(); // Refresh chart and table
        alert('Balance deleted successfully!');
    } catch (error) {
        console.error('Error deleting balance:', error);
        alert(`Error: ${error.message}`);
    }
}

if (typeof window !== 'undefined') {
    window.loadUserData = loadUserData;
    window.loadSingleUser = loadSingleUser;
    window.showBalanceForm = showBalanceForm;
    window.hideBalanceForm = hideBalanceForm;
    window.submitBalance = submitBalance;
    window.editBalance = editBalance;
    window.hideEditBalanceForm = hideEditBalanceForm;
    window.submitEditBalance = submitEditBalance;
    window.deleteBalance = deleteBalance;
    window.recalculateStressTest = recalculateStressTest;
    window.loadStressTestResult = loadStressTestResult;
    window.renderSingleUserChart = renderSingleUserChart;
    window.renderDeltaTable = renderDeltaTable;
    window.toggleStressMode = toggleStressMode;
    window.loadJointStressTestResult = loadJointStressTestResult;
    window.recalculateJointStressTest = recalculateJointStressTest;
    window.toggleAssumptions = toggleAssumptions;
}
