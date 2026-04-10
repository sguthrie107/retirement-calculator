// Chart.js initialization and data management

let chartInstance = null;
let projectedAccountBalancesByYear = {};
let actualAccountBalancesByYear = {};
let projectedTotalsByYear = {};
let actualTotalsByYear = {};
let currentSingleUsername = null;
let currentSingleUserData = null;
let currentSingleUserMatchScenarios = null;
let currentAllUsersData = null;
let selectedDeductionRate = 0.05;
let isStandardDeductionEnabled = false;

// ── Benchmark comparison state ─────────────────────────────────────────────
const _benchmarkCache  = {};   // keyed "username_year"  → API response payload
const _benchmarkCharts = {};   // keyed "username_year"  → Chart.js instance

if (window.Chart) {
    Chart.defaults.font.family = 'Montserrat, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
    Chart.defaults.color = '#475569';
}

// Color palette for multiple users
const userColors = {
    'Steven': { border: '#1F3A8A', bg: 'rgba(31, 58, 138, 0.12)' },
    'Alyssa': { border: '#C8A44D', bg: 'rgba(200, 164, 77, 0.14)' },
    'Steven+Alyssa': { border: '#7C3AED', bg: 'rgba(124, 58, 237, 0.14)' },
    'Alyssa+Steven': { border: '#7C3AED', bg: 'rgba(124, 58, 237, 0.14)' },
    'Steven + Alyssa Portfolio': { border: '#7C3AED', bg: 'rgba(124, 58, 237, 0.14)' },
    'User3': { border: '#06B6D4', bg: 'rgba(6, 182, 212, 0.1)' },
    'User4': { border: '#8B5CF6', bg: 'rgba(139, 92, 246, 0.1)' },
};

const sequenceRiskReturns = [-0.18, -0.10, -0.05, 0.00, 0.03, 0.05, 0.04, 0.03, 0.03, 0.025];

function getSequenceRiskReturn(startYear, year) {
    const offset = Math.max(0, year - startYear);
    if (offset < sequenceRiskReturns.length) {
        return sequenceRiskReturns[offset];
    }
    return 0.03;
}

function buildPostRetirementSeries(baseByYear, retirementYear, lifeExpectancyYear, deductionRate) {
    const output = {};
    if (!Number.isFinite(retirementYear) || !Number.isFinite(lifeExpectancyYear) || lifeExpectancyYear < retirementYear) {
        return output;
    }

    const startBalance = Number(baseByYear[retirementYear] ?? 0);
    let runningBalance = Math.max(startBalance, 0);
    const fixedAnnualWithdrawal = Math.max(startBalance * deductionRate, 0);
    output[retirementYear] = roundToCents(runningBalance);

    for (let year = retirementYear + 1; year <= lifeExpectancyYear; year += 1) {
        const riskReturn = getSequenceRiskReturn(retirementYear, year);
        runningBalance = Math.max(runningBalance * (1 + riskReturn), 0);
        const withdrawal = Math.min(fixedAnnualWithdrawal, runningBalance);
        runningBalance = Math.max(runningBalance - withdrawal, 0);
        output[year] = roundToCents(runningBalance);
    }

    return output;
}

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

function getSelectedDeductionRate() {
    const select = document.getElementById('deductionRateSelect');
    const value = select ? Number(select.value) : selectedDeductionRate;
    if (Number.isFinite(value) && value > 0) {
        return value;
    }
    return selectedDeductionRate;
}

function syncDeductionControls() {
    const toggle = document.getElementById('standardDeductionToggle');

    if (toggle) {
        toggle.checked = Boolean(isStandardDeductionEnabled);
    }
}

function onStandardDeductionToggleChange() {
    const toggle = document.getElementById('standardDeductionToggle');
    isStandardDeductionEnabled = Boolean(toggle?.checked);
    syncDeductionControls();
    const userSelect = document.getElementById('userSelect');
    const selectedUser = userSelect ? userSelect.value : currentSingleUsername;
    if (selectedUser && selectedUser !== 'all') {
        loadSingleUser(selectedUser);
        return;
    }
    rerenderCurrentUserChart();
}

function onDeductionRateChange() {
    selectedDeductionRate = getSelectedDeductionRate();
    if (!isStandardDeductionEnabled) {
        isStandardDeductionEnabled = true;
        const toggle = document.getElementById('standardDeductionToggle');
        if (toggle) toggle.checked = true;
    }
    syncDeductionControls();
    const userSelect = document.getElementById('userSelect');
    const selectedUser = userSelect ? userSelect.value : currentSingleUsername;
    if (selectedUser && selectedUser !== 'all') {
        loadSingleUser(selectedUser);
        return;
    }
    rerenderCurrentUserChart();
}

function rerenderCurrentUserChart() {
    if (currentSingleUsername && currentSingleUserData) {
        renderSingleUserChart(currentSingleUsername, currentSingleUserData, currentSingleUserMatchScenarios);
    }
}

function resolveHouseholdUsernameFromSelect() {
    const userSelect = document.getElementById('userSelect');
    if (!userSelect) {
        return 'Steven+Alyssa';
    }

    const candidateValues = Array.from(userSelect.options || []).map((opt) => String(opt.value || '').trim());
    const normalized = candidateValues.map((value) => value.replace(/\s+/g, '').toLowerCase());

    const preferred = ['alyssa+steven', 'steven+alyssa'];
    for (const target of preferred) {
        const idx = normalized.findIndex((value) => value === target);
        if (idx >= 0) {
            return candidateValues[idx];
        }
    }

    const fuzzyIdx = normalized.findIndex((value) => value.includes('steven') && value.includes('alyssa'));
    if (fuzzyIdx >= 0) {
        return candidateValues[fuzzyIdx];
    }

    return 'Steven+Alyssa';
}

function formatSignedPct(value) {
    if (!Number.isFinite(Number(value))) return '—';
    const numeric = Number(value);
    const sign = numeric > 0 ? '+' : '';
    return `${sign}${numeric.toFixed(2)}%`;
}

function formatSignedCurrency(value) {
    if (!Number.isFinite(Number(value))) return '—';
    const numeric = Number(value);
    const sign = numeric > 0 ? '+' : '';
    return `${sign}${formatCurrency(Math.abs(numeric))}`;
}

function getTrendClass(change) {
    if (!Number.isFinite(Number(change))) return '';
    const numeric = Number(change);
    if (numeric > 0) return 'trend-up';
    if (numeric < 0) return 'trend-down';
    return '';
}

function renderHoldingsCard(payload) {
    const section = document.getElementById('holdingsSection');
    const content = document.getElementById('holdingsContent');
    const asOf = document.getElementById('holdingsAsOf');
    if (!section || !content) {
        return;
    }

    section.style.display = 'block';

    if (!payload || !Array.isArray(payload.holdings) || payload.holdings.length === 0) {
        if (asOf) {
            asOf.textContent = '';
        }
        content.innerHTML = '<p class="loading">No holdings configured for the current phase.</p>';
        return;
    }

    const asOfText = payload.as_of_date ? `As of ${payload.as_of_date} • Year ${payload.as_of_year}` : '';
    if (asOf) {
        asOf.textContent = asOfText;
    }

    const rowsHtml = payload.holdings.map((row) => {
        const trendClass = getTrendClass(row.day_change_pct);
        const priceDisplay = Number.isFinite(Number(row.price)) ? formatCurrency(Number(row.price)) : '—';
        return `
            <tr>
                <td>${row.account_type === '401k' ? '401k' : 'IRA'}</td>
                <td>${row.ticker}</td>
                <td>${row.label || row.ticker}</td>
                <td>${Number(row.allocation_pct || 0).toFixed(1)}%</td>
                <td>${Number(row.portfolio_weight_pct || 0).toFixed(1)}%</td>
                <td>${priceDisplay}</td>
                <td class="${trendClass}">${formatSignedCurrency(row.day_change)}</td>
                <td class="${trendClass}">${formatSignedPct(row.day_change_pct)}</td>
            </tr>
        `;
    }).join('');

    content.innerHTML = `
        <table class="holdings-table">
            <thead>
                <tr>
                    <th>Account</th>
                    <th>Ticker</th>
                    <th>Fund</th>
                    <th>Acct Weight</th>
                    <th>Portfolio Wt</th>
                    <th>Price</th>
                    <th>Day $</th>
                    <th>Day %</th>
                </tr>
            </thead>
            <tbody>${rowsHtml}</tbody>
        </table>
    `;
}

async function loadHoldings(username) {
    const section = document.getElementById('holdingsSection');
    const content = document.getElementById('holdingsContent');
    const asOf = document.getElementById('holdingsAsOf');
    if (!section || !content) {
        return;
    }

    section.style.display = 'block';
    if (asOf) {
        asOf.textContent = '';
    }

    if (String(username || '').includes('+') || String(username || '').includes(',')) {
        content.innerHTML = '<p class="loading">Holdings are available for individual user views.</p>';
        return;
    }

    content.innerHTML = '<p class="loading">Loading holdings...</p>';

    try {
        const response = await fetch(`/api/holdings/${username}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const payload = await response.json();
        renderHoldingsCard(payload);
    } catch (error) {
        content.innerHTML = `<p class="loading" style="color: #9A3412;">Unable to load holdings: ${error.message}</p>`;
    }
}

async function loadUserData() {
    const userSelect = document.getElementById('userSelect');
    let selectedValue = userSelect ? String(userSelect.value || '').trim() : '';

    if (selectedValue.toLowerCase() === 'all') {
        selectedValue = resolveHouseholdUsernameFromSelect();
        if (userSelect) {
            userSelect.value = selectedValue;
        }
    }

    console.log('loadUserData called - userSelect value:', selectedValue);
    
    if (!selectedValue) {
        console.log('No user selected');
        const holdingsSection = document.getElementById('holdingsSection');
        if (holdingsSection) {
            holdingsSection.style.display = 'none';
        }
        return;
    }
    
    const addBalanceBtn = document.getElementById('addBalanceBtn');
    const deltaTable = document.getElementById('deltaTable');
    const stressTestSection = document.getElementById('stressTestSection');
    
    console.log('Loading single user:', selectedValue);
    addBalanceBtn.style.display = 'inline-block';
    deltaTable.style.display = 'block';
    if (stressTestSection) {
        stressTestSection.style.display = 'block';
    }
    const deductionControlGroup = document.getElementById('deductionControlGroup');
    if (deductionControlGroup) {
        deductionControlGroup.style.display = 'flex';
    }
    syncDeductionControls();
    loadSingleUser(selectedValue);
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

        currentSingleUsername = username;
        currentSingleUserData = data;
        currentSingleUserMatchScenarios = matchScenarios;
        currentAllUsersData = null;
        selectedDeductionRate = getSelectedDeductionRate();
        const deductionRateSelect = document.getElementById('deductionRateSelect');
        if (deductionRateSelect) {
            deductionRateSelect.value = String(selectedDeductionRate);
        }
        syncDeductionControls();

        renderSingleUserChart(username, data, matchScenarios);
        renderDeltaTable(data.deltas);
        await loadHoldings(username);
        await syncStressTestUiForSelection(username);
    } catch (error) {
        console.error('Error loading user data:', error);
        document.getElementById('deltaContent').innerHTML = 
            `<p class="loading" style="color: #9A3412;">Error loading data: ${error.message}</p>`;
        document.getElementById('retirementChart').innerHTML =
            `<p class="loading" style="color: #9A3412;">Error loading data: ${error.message}</p>`;
        const holdingsContent = document.getElementById('holdingsContent');
        const holdingsSection = document.getElementById('holdingsSection');
        if (holdingsSection) {
            holdingsSection.style.display = 'block';
        }
        if (holdingsContent) {
            holdingsContent.innerHTML = `<p class="loading" style="color: #9A3412;">Error loading holdings: ${error.message}</p>`;
        }
    }
}

async function loadAllUsers() {
    try {
        const response = await fetch(`/api/comparison-all`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        currentSingleUsername = null;
        currentSingleUserData = null;
        currentSingleUserMatchScenarios = null;
        currentAllUsersData = data.users || [];
        renderAllUsersChart(currentAllUsersData);
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
    
    // Extract years from projected + actual data so actual-only years render on chart
    const projectedYears = data.projected
        .map((point) => Number(point.year))
        .filter((year) => Number.isFinite(year) && year > 0);
    const actualYears = data.actual
        .map((point) => Number(point.year))
        .filter((year) => Number.isFinite(year) && year > 0);
    const baseYears = Array.from(new Set([...projectedYears, ...actualYears])).sort((a, b) => a - b);
    
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
    
    const projectedData = baseYears.map((year) => (
        Object.prototype.hasOwnProperty.call(projectedTotalsByYear, year)
            ? projectedTotalsByYear[year]
            : null
    ));
    const actualData = baseYears.map(year => actualByYear[year] || null);
    const toNumber = (value) => {
        if (value === null || value === undefined || value === '') return 0;
        if (typeof value === 'number') return Number.isFinite(value) ? value : 0;
        const parsed = Number(String(value).replace(/,/g, ''));
        return Number.isFinite(parsed) ? parsed : 0;
    };
    const getAccountBalanceValue = (balances, keys) => {
        const matchedKey = keys.find((key) => Object.prototype.hasOwnProperty.call(balances, key));
        if (!matchedKey) {
            return null;
        }
        return toNumber(balances[matchedKey]);
    };

    const firstProjectedBreakdown = data.projected
        .map((d) => d.account_balances || {})
        .find((b) => toNumber(b['401k'] ?? b['k401'] ?? b['401K']) > 0 || toNumber(b['roth_ira'] ?? b['ira'] ?? b['IRA'] ?? b['rothIra']) > 0);
    const firstActualBreakdown = baseYears
        .map((year) => actualAccountBalancesByYear[year] || {})
        .find((b) => toNumber(b['401k'] ?? b['k401'] ?? b['401K']) > 0 || toNumber(b['roth_ira'] ?? b['ira'] ?? b['IRA'] ?? b['rothIra']) > 0);

    const seed401k = toNumber((firstProjectedBreakdown || firstActualBreakdown || {})['401k'] ?? (firstProjectedBreakdown || firstActualBreakdown || {})['k401'] ?? (firstProjectedBreakdown || firstActualBreakdown || {})['401K']);
    const seedIra = toNumber((firstProjectedBreakdown || firstActualBreakdown || {})['roth_ira'] ?? (firstProjectedBreakdown || firstActualBreakdown || {})['ira'] ?? (firstProjectedBreakdown || firstActualBreakdown || {})['IRA'] ?? (firstProjectedBreakdown || firstActualBreakdown || {})['rothIra']);
    const seedTotal = seed401k + seedIra;
    const default401kWeight = seedTotal > 0 ? (seed401k / seedTotal) : 0.6;
    const defaultIraWeight = 1 - default401kWeight;

    const projected401kData = baseYears.map((year, idx) => {
        const balances = projectedAccountBalancesByYear[year] || {};
        const projectedTotal = toNumber(projectedData[idx]);
        const direct401k = toNumber(balances['401k'] ?? balances['k401'] ?? balances['401K']);
        const directIra = toNumber(balances['roth_ira'] ?? balances['ira'] ?? balances['IRA'] ?? balances['rothIra']);

        if (direct401k > 0) return direct401k;
        if (projectedTotal > 0 && directIra > 0) return Math.max(projectedTotal - directIra, 0);
        if (projectedTotal > 0) return projectedTotal * default401kWeight;
        return 0;
    });
    const projectedIraData = baseYears.map((year, idx) => {
        const balances = projectedAccountBalancesByYear[year] || {};
        const projectedTotal = toNumber(projectedData[idx]);
        const direct401k = toNumber(balances['401k'] ?? balances['k401'] ?? balances['401K']);
        const directIra = toNumber(balances['roth_ira'] ?? balances['ira'] ?? balances['IRA'] ?? balances['rothIra']);

        if (directIra > 0) return directIra;
        if (projectedTotal > 0 && direct401k > 0) return Math.max(projectedTotal - direct401k, 0);
        if (projectedTotal > 0) return projectedTotal * defaultIraWeight;
        return 0;
    });
    const actual401kData = baseYears.map((year) => {
        const balances = actualAccountBalancesByYear[year] || {};
        return getAccountBalanceValue(balances, ['401k', 'k401', '401K']);
    });
    const actualIraData = baseYears.map((year) => {
        const balances = actualAccountBalancesByYear[year] || {};
        return getAccountBalanceValue(balances, ['roth_ira', 'ira', 'IRA', 'rothIra']);
    });
    const actualAboveData = baseYears.map((year, idx) => {
        const actual = actualData[idx];
        const projected = projectedData[idx];
        if (actual === null || projected === null || projected === undefined) {
            return null;
        }
        return actual >= projected ? actual : null;
    });
    const actualBelowData = baseYears.map((year, idx) => {
        const actual = actualData[idx];
        const projected = projectedData[idx];
        if (actual === null || projected === null || projected === undefined) {
            return null;
        }
        return actual < projected ? actual : null;
    });
    const differencePointColors = baseYears.map((year, idx) => {
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
    const retirementAge = Number(data.retirement_age || 65);
    const retirementYearValue = Number.isFinite(Number(retirementYear)) ? Number(retirementYear) : Number(data.retirement_year || 0);
    const lifeExpectancyAge = Number(data.life_expectancy_age || 88);
    const deductionRate = getSelectedDeductionRate();
    const deductionToggle = document.getElementById('standardDeductionToggle');
    const deductionEnabled = Boolean(deductionToggle?.checked);

    const chartYears = [...baseYears];
    const postRetirementByYear = {};
    const baselineWithdrawalByYear = {};
    const scenarioWithdrawalByKey = {
        '3pct': {},
        '5pct': {},
    };

    let lifeExpectancyYear = null;
    if (deductionEnabled && Number.isFinite(retirementYearValue) && retirementYearValue > 0 && Number.isFinite(retirementAge) && Number.isFinite(lifeExpectancyAge)) {
        const currentYearApprox = retirementYearValue - retirementAge;
        lifeExpectancyYear = currentYearApprox + lifeExpectancyAge;
        const projectionByYear = {};
        baseYears.forEach((year, idx) => {
            projectionByYear[year] = projectedData[idx];
        });

        const startYear = retirementYearValue;
        const startBalance = Number(projectionByYear[startYear] ?? projectedData[projectedData.length - 1] ?? 0);
        const fixedAnnualWithdrawal = Math.max(startBalance * deductionRate, 0);
        let runningBalance = Math.max(startBalance, 0);
        postRetirementByYear[startYear] = roundToCents(runningBalance);
        baselineWithdrawalByYear[startYear] = 0;

        for (let year = startYear + 1; year <= lifeExpectancyYear; year += 1) {
            const riskReturn = getSequenceRiskReturn(startYear, year);
            runningBalance = Math.max(runningBalance * (1 + riskReturn), 0);
            const withdrawal = Math.min(fixedAnnualWithdrawal, runningBalance);
            runningBalance = Math.max(runningBalance - withdrawal, 0);
            postRetirementByYear[year] = roundToCents(runningBalance);
            baselineWithdrawalByYear[year] = roundToCents(withdrawal);
            if (!chartYears.includes(year)) {
                chartYears.push(year);
            }
        }
    }

    chartYears.sort((a, b) => a - b);

    const projectedByYear = {};
    baseYears.forEach((year, idx) => {
        projectedByYear[year] = projectedData[idx];
    });

    const projectedDisplaySeries = chartYears.map((year) => {
        if (deductionEnabled && Number.isFinite(retirementYearValue) && year >= retirementYearValue) {
            if (Object.prototype.hasOwnProperty.call(postRetirementByYear, year)) {
                return postRetirementByYear[year];
            }
            return null;
        }
        if (Object.prototype.hasOwnProperty.call(projectedByYear, year)) {
            return projectedByYear[year];
        }
        return null;
    });

    const actualDisplaySeries = chartYears.map((year) => {
        if (Object.prototype.hasOwnProperty.call(actualByYear, year)) {
            return actualByYear[year];
        }
        return null;
    });

    if (matchScenarios) {
        const scenarioConfigs = [
            { key: '3pct', label: '+3% 401k Contribution', color: '#0F766E', order: 2 },
            { key: '5pct', label: '+5% 401k Contribution', color: '#7C3AED', order: 3 },
        ];
        for (const cfg of scenarioConfigs) {
            if (matchScenarios[cfg.key]) {
                const byYear = {};
                matchScenarios[cfg.key].forEach(d => { byYear[d.year] = d.balance; });

                if (deductionEnabled && Number.isFinite(retirementYearValue) && retirementYearValue > 0 && Number.isFinite(lifeExpectancyYear)) {
                    const scenarioStartBalance = Number(
                        byYear[retirementYearValue]
                        ?? byYear[Math.max(...Object.keys(byYear).map(Number).filter(y => y <= retirementYearValue))]
                        ?? 0
                    );
                    const scenarioFixedWithdrawal = Math.max(scenarioStartBalance * deductionRate, 0);
                    let scenarioRunningBalance = Math.max(scenarioStartBalance, 0);
                    byYear[retirementYearValue] = roundToCents(scenarioRunningBalance);
                    scenarioWithdrawalByKey[cfg.key][retirementYearValue] = 0;

                    for (let year = retirementYearValue + 1; year <= lifeExpectancyYear; year += 1) {
                        const scenarioRiskReturn = getSequenceRiskReturn(retirementYearValue, year);
                        scenarioRunningBalance = Math.max(scenarioRunningBalance * (1 + scenarioRiskReturn), 0);
                        const scenarioWithdrawal = Math.min(scenarioFixedWithdrawal, scenarioRunningBalance);
                        scenarioRunningBalance = Math.max(scenarioRunningBalance - scenarioWithdrawal, 0);
                        byYear[year] = roundToCents(scenarioRunningBalance);
                        scenarioWithdrawalByKey[cfg.key][year] = roundToCents(scenarioWithdrawal);
                    }
                }

                matchDatasets.push({
                    label: cfg.label,
                    data: chartYears.map(y => byYear[y] ?? null),
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

    const resolveTooltipIndex = (context) => {
        if (!context || context.length === 0) {
            return null;
        }
        const dataIndex = Number(context[0]?.dataIndex);
        return Number.isFinite(dataIndex) ? dataIndex : null;
    };

    chartInstance = new Chart(ctx, {
        type: 'line',
        plugins: [retirementMarkerPlugin],
        data: {
            labels: chartYears,
            datasets: [
                ...matchDatasets,
                {
                    label: deductionEnabled
                        ? `${username} - Projected Balance (${Math.round(deductionRate * 100)}% Standard Deduction)`
                        : `${username} - Projected Balance`,
                    data: projectedDisplaySeries,
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
                    data: actualDisplaySeries,
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
                            const idx = resolveTooltipIndex(context);
                            const year = idx !== null ? chartYears[idx] : context[0].label;
                            return 'Year ' + year;
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

                            const idx = resolveTooltipIndex(context);
                            if (idx === null) {
                                return '';
                            }

                            const hoverYear = Number(chartYears[idx]);
                            const isPostRetirementView = deductionEnabled
                                && Number.isFinite(retirementYearValue)
                                && hoverYear > retirementYearValue;

                            const formatMoney = (value) => new Intl.NumberFormat('en-US', {
                                style: 'currency',
                                currency: 'USD',
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            }).format(value || 0);

                            const rows = [];

                            if (isPostRetirementView) {
                                rows.push(`Withdrawal Rate: ${(deductionRate * 100).toFixed(1)}%`);
                                rows.push('Total Withdraw: ' + formatMoney(baselineWithdrawalByYear[hoverYear] || 0));

                                if (scenarioWithdrawalByKey['3pct'] && scenarioWithdrawalByKey['3pct'][hoverYear] !== undefined) {
                                    rows.push('+3% Withdraw: ' + formatMoney(scenarioWithdrawalByKey['3pct'][hoverYear]));
                                }
                                if (scenarioWithdrawalByKey['5pct'] && scenarioWithdrawalByKey['5pct'][hoverYear] !== undefined) {
                                    rows.push('+5% Withdraw: ' + formatMoney(scenarioWithdrawalByKey['5pct'][hoverYear]));
                                }

                                const postRetirementBalance = projectedDisplaySeries[idx];
                                if (postRetirementBalance !== undefined && postRetirementBalance !== null) {
                                    rows.push('Projected End Balance: ' + formatMoney(postRetirementBalance));
                                }

                                return rows;
                            }

                            const projectedTotal = projectedDisplaySeries[idx];
                            if (projectedTotal !== undefined && projectedTotal !== null) {
                                const projected401k = projected401kData[idx] !== undefined ? projected401kData[idx] : (projectedTotal * default401kWeight);
                                const projectedIra = projectedIraData[idx] !== undefined ? projectedIraData[idx] : (projectedTotal * defaultIraWeight);
                                rows.push('Projected (401k): ' + formatMoney(projected401k));
                                rows.push('Projected (IRA): ' + formatMoney(projectedIra));
                            }

                            const actualTotal = actualDisplaySeries[idx];
                            if (actualTotal !== undefined && actualTotal !== null) {
                                rows.push('Actual (Total): ' + formatMoney(actualTotal));
                                if (actual401kData[idx] !== undefined && actual401kData[idx] !== null) {
                                    rows.push('Actual (401k): ' + formatMoney(actual401kData[idx]));
                                }
                                if (actualIraData[idx] !== undefined && actualIraData[idx] !== null) {
                                    rows.push('Actual (IRA): ' + formatMoney(actualIraData[idx]));
                                }
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

function roundToCents(value) {
    return Math.round((Number(value) || 0) * 100) / 100;
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
    
    const yearsSet = new Set();
    const deductionEnabled = Boolean(document.getElementById('standardDeductionToggle')?.checked);
    const deductionRate = getSelectedDeductionRate();
    const parsedUsers = usersData.map((user, index) => {
        const colors = userColors[user.username] || {
            border: `hsl(${(index * 60) % 360}, 70%, 50%)`,
            bg: `hsla(${(index * 60) % 360}, 70%, 50%, 0.1)`
        };

        const projectedByYear = {};
        const projectedAccountsByYear = {};
        const actualByYear = {};
        const actualAccountsByYear = {};

        (user.projected || []).forEach((point) => {
            if (!Number.isFinite(Number(point.year))) return;
            const year = Number(point.year);
            projectedByYear[year] = Number(point.balance ?? 0);
            projectedAccountsByYear[year] = point.account_balances || {};
            yearsSet.add(year);
        });

        (user.actual || []).forEach((point) => {
            if (!Number.isFinite(Number(point.year))) return;
            const year = Number(point.year);
            actualByYear[year] = Number(point.balance ?? 0);
            actualAccountsByYear[year] = point.account_balances || {};
            yearsSet.add(year);
        });

        const retirementYear = Number(user.retirement_year || 0);
        const lifeExpectancyAge = Number(user.life_expectancy_age || 0);
        let lifeExpectancyYear = null;
        if (Number.isFinite(retirementYear) && retirementYear > 0 && Number.isFinite(lifeExpectancyAge) && lifeExpectancyAge > 0) {
            const retirementAge = Number(user.retirement_age || 0);
            if (Number.isFinite(retirementAge) && retirementAge > 0) {
                const currentYearApprox = retirementYear - retirementAge;
                lifeExpectancyYear = currentYearApprox + lifeExpectancyAge;
            }
        }

        if (deductionEnabled && Number.isFinite(lifeExpectancyYear) && Number.isFinite(retirementYear) && retirementYear > 0) {
            const postSeries = buildPostRetirementSeries(projectedByYear, retirementYear, lifeExpectancyYear, deductionRate);
            Object.keys(postSeries).forEach((yearKey) => {
                const year = Number(yearKey);
                projectedByYear[year] = postSeries[year];
                yearsSet.add(year);
            });
        }

        return {
            username: user.username,
            colors,
            projectedByYear,
            projectedAccountsByYear,
            actualByYear,
            actualAccountsByYear,
            isPortfolio: Boolean(user.is_portfolio),
        };
    });

    const years = Array.from(yearsSet).sort((a, b) => a - b);

    if (years.length === 0) {
        document.getElementById('retirementChart').innerHTML = '<p class="loading">No projected data available</p>';
        return;
    }

    console.log('All users comparison - Year range:', years[0], 'to', years[years.length - 1], ', Total years:', years.length);

    const datasets = [];
    parsedUsers.forEach((user) => {
        const projectedSeries = years.map((year) => Object.prototype.hasOwnProperty.call(user.projectedByYear, year) ? user.projectedByYear[year] : null);
        datasets.push({
            label: `${user.username} - Projected`,
            data: projectedSeries,
            borderColor: user.colors.border,
            backgroundColor: user.colors.bg,
            borderWidth: user.isPortfolio ? 3 : 2.5,
            fill: true,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: isMobileViewport ? 7 : 10,
            pointHoverBorderColor: '#FFFFFF',
            pointHoverBorderWidth: 2,
            spanGaps: true,
            custom: {
                username: user.username,
                seriesType: 'projected',
                accountByYear: user.projectedAccountsByYear,
            },
        });

        const hasActual = Object.keys(user.actualByYear).length > 0;
        if (hasActual) {
            const actualSeries = years.map((year) => Object.prototype.hasOwnProperty.call(user.actualByYear, year) ? user.actualByYear[year] : null);
            datasets.push({
                label: `${user.username} - Actual`,
                data: actualSeries,
                borderColor: user.colors.border,
                backgroundColor: user.colors.bg,
                borderWidth: user.isPortfolio ? 2.6 : 2.2,
                borderDash: [8, 5],
                fill: false,
                tension: 0.4,
                pointRadius: isMobileViewport ? 3 : 5,
                pointHoverRadius: isMobileViewport ? 7 : 10,
                pointHoverBorderColor: '#FFFFFF',
                pointHoverBorderWidth: 2,
                spanGaps: true,
                custom: {
                    username: user.username,
                    seriesType: 'actual',
                    accountByYear: user.actualAccountsByYear,
                },
            });
        }
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
                        boxWidth: isMobileViewport ? 14 : 20,
                        boxHeight: isMobileViewport ? 8 : 12,
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
                            return 'Year ' + (context?.[0]?.label ?? '');
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
                        afterLabel: function(context) {
                            const year = Number(context.label);
                            const custom = context.dataset.custom || {};
                            const accountByYear = custom.accountByYear || {};
                            const balances = accountByYear[year] || {};
                            const k401 = Number(balances['401k'] ?? balances['k401'] ?? balances['401K'] ?? 0);
                            const ira = Number(balances['roth_ira'] ?? balances['ira'] ?? balances['IRA'] ?? balances['rothIra'] ?? 0);

                            if (k401 <= 0 && ira <= 0) {
                                return [];
                            }

                            const formatCurrency = (value) => new Intl.NumberFormat('en-US', {
                                style: 'currency',
                                currency: 'USD',
                                minimumFractionDigits: 2,
                                maximumFractionDigits: 2,
                            }).format(value);

                            return [
                                `401k: ${formatCurrency(k401)}`,
                                `Roth IRA: ${formatCurrency(ira)}`,
                            ];
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

function renderDeltaTable(deltas) {
    const content = document.getElementById('deltaContent');
    
    if (!deltas || deltas.length === 0) {
        content.innerHTML = '<p class="loading">No actual balance data entered yet. Add balances to see comparison.</p>';
        return;
    }
    
    console.log('renderDeltaTable - deltas received:', deltas);

    // Destroy any lingering benchmark chart instances when the user switches
    Object.keys(_benchmarkCharts).forEach(k => {
        try { _benchmarkCharts[k].destroy(); } catch (_) {}
        delete _benchmarkCharts[k];
    });

    const COL_COUNT = 8; // year, projected, actual, diff$, diff%, updated, actions, compare
    
    let html = '<table class="performance-comparison-table"><thead><tr>';
    html += '<th>Year</th>';
    html += '<th>Projected</th>';
    html += '<th>Actual</th>';
    html += '<th>Difference ($)</th>';
    html += '<th>Difference (%)</th>';
    html += '<th>Last Updated</th>';
    html += '<th>Actions</th>';
    html += '<th>vs. Benchmark</th>';
    html += '</tr></thead><tbody>';
    
    deltas.forEach((delta, idx) => {
        const hasProjected = delta.has_projection !== false;
        const hasDelta = hasProjected && Number.isFinite(Number(delta.delta));
        const diffClass = !hasDelta ? '' : (delta.delta >= 0 ? 'positive' : 'negative');
        const diffSign = hasDelta && delta.delta >= 0 ? '+' : '';
        const balanceIdStr = delta.balance_ids ? delta.balance_ids.join(',') : '';
        const panelId  = `bm-panel-${delta.year}`;
        const canvasId = `bm-canvas-${delta.year}`;
        
        // Format timestamp to EST timezone
        let timestampDisplay = '-';
        if (delta.timestamp) {
            try {
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
        
        // ── Data row ──────────────────────────────────────────────────────────
        const stripeClass = idx % 2 === 0 ? 'comparison-row-odd' : 'comparison-row-even';
        html += `<tr class="comparison-data-row ${stripeClass}">`;
        html += `<td><strong>${delta.year}</strong></td>`;
        html += `<td>${hasProjected ? formatCurrency(delta.projected) : '—'}</td>`;
        html += `<td>${formatCurrency(delta.actual)}</td>`;
        html += `<td class="${diffClass}">${hasDelta ? `${diffSign}${formatCurrency(delta.delta)}` : '—'}</td>`;
        html += `<td class="${diffClass}">${hasDelta ? `${diffSign}${Number(delta.delta_pct).toFixed(2)}%` : '—'}</td>`;
        html += `<td>${timestampDisplay}</td>`;
        html += `<td class="action-buttons">
                    <button type="button" class="btn-edit" data-balance-ids="${balanceIdStr}" data-year="${delta.year}" data-balance="${delta.actual}" title="Edit">✏️</button>
                    <button type="button" class="btn-delete" onclick="handleDeleteClick('${balanceIdStr}', ${delta.year})" title="Delete">🗑️</button>
                </td>`;
        html += `<td>
                    <button class="btn-benchmark-expand"
                            id="bm-btn-${delta.year}"
                            onclick="toggleBenchmarkRow(${delta.year})"
                            title="Compare to Boglehead 3-Fund Portfolio">
                        <i class="expand-arrow">▶</i> Compare
                    </button>
                </td>`;
        html += '</tr>';

        // ── Expandable detail row (hidden by default) ────────────────────────
        html += `<tr class="benchmark-detail-row" id="bm-row-${delta.year}">`;
        html += `<td colspan="${COL_COUNT}">`;
        html += `<div class="benchmark-detail-panel" id="${panelId}">`;
        html += `<div class="benchmark-detail-inner">`;
        html += `<div class="bm-loading" id="bm-loading-${delta.year}">Loading benchmark data…</div>`;
        html += `</div></div></td></tr>`;
    });
    
    html += '</tbody></table>';
    content.innerHTML = html;
    
    // Attach event listeners to edit buttons (inline onclick can't close over objects)
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

// ── Benchmark expand / collapse ───────────────────────────────────────────────

async function toggleBenchmarkRow(year) {
    const panel = document.getElementById(`bm-panel-${year}`);
    const btn   = document.getElementById(`bm-btn-${year}`);
    if (!panel || !btn) return;

    const isOpen = panel.classList.contains('open');

    if (isOpen) {
        panel.classList.remove('open');
        btn.classList.remove('open');
    } else {
        panel.classList.add('open');
        btn.classList.add('open');

        const username = currentSingleUsername;
        if (!username) return;

        const cacheKey = `${username}_${year}`;
        if (_benchmarkCache[cacheKey]) {
            _renderBenchmarkPanel(year, _benchmarkCache[cacheKey]);
        } else {
            await _fetchAndRenderBenchmark(username, year);
        }
    }
}

async function _fetchAndRenderBenchmark(username, year) {
    const cacheKey  = `${username}_${year}`;
    try {
        const response = await fetch(`/api/benchmark/${encodeURIComponent(username)}/${year}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        const data = await response.json();
        _benchmarkCache[cacheKey] = data;
        _renderBenchmarkPanel(year, data);
    } catch (err) {
        console.error(`Benchmark fetch failed for ${username}/${year}:`, err);
        const inner = document.querySelector(`#bm-panel-${year} .benchmark-detail-inner`);
        if (inner) {
            inner.innerHTML = `<div class="bm-error">⚠ Could not load benchmark data: ${err.message}<br><small>Ensure the server can reach Yahoo Finance for this year's data.</small></div>`;
        }
    }
}

function _renderBenchmarkPanel(year, data) {
    const panelInner = document.querySelector(`#bm-panel-${year} .benchmark-detail-inner`);
    if (!panelInner) return;

    const canvasId = `bm-canvas-${year}`;
    const username = data.username || currentSingleUsername || 'Portfolio';
    const cacheKey = `${username}_${year}`;

    const user  = data.user_portfolio || {};
    const bog   = data.boglehead      || {};
    const f2060 = data.freedom_2060   || {};

    const userRet  = typeof user.annual_return_pct  === 'number' ? user.annual_return_pct  : null;
    const bogRet   = typeof bog.annual_return_pct   === 'number' ? bog.annual_return_pct   : null;
    const f2060Ret = typeof f2060.annual_return_pct === 'number' ? f2060.annual_return_pct : null;
    const alpha    = typeof data.alpha_pct           === 'number' ? data.alpha_pct           : null;

    const fmt1 = v => v !== null ? `${v >= 0 ? '+' : ''}${v.toFixed(2)}%` : '—';
    const cls  = v => v === null ? 'neutral' : (v >= 0 ? 'positive' : 'negative');

    // ── Stat cards ─────────────────────────────────────────────────────────
    const badgeHtml = alpha !== null
        ? `<span class="bm-badge ${data.outperformed ? 'outperformed' : 'underperformed'}">
             ${data.outperformed ? '▲ Outperformed' : '▼ Underperformed'}
           </span>`
        : '';

    const statsHtml = `
        <div class="benchmark-stats">
            <div class="bm-stat-card">
                <div class="stat-label">${username}'s Return (${year})</div>
                <div class="stat-value ${cls(userRet)}">${fmt1(userRet)}</div>
                <div class="stat-sub">${user.allocation_label || ''}</div>
            </div>
            <div class="bm-stat-card">
                <div class="stat-label">Boglehead 3-Fund (${year})</div>
                <div class="stat-value ${cls(bogRet)}">${fmt1(bogRet)}</div>
                <div class="stat-sub">VTI 60% / VXUS 20% / BND 20%</div>
            </div>
            <div class="bm-stat-card">
                <div class="stat-label">Fidelity Freedom 2060 (${year})</div>
                <div class="stat-value ${cls(f2060Ret)}">${fmt1(f2060Ret)}</div>
                <div class="stat-sub">FDKLX — target date fund</div>
            </div>
            <div class="bm-stat-card">
                <div class="stat-label">Alpha vs Boglehead</div>
                <div class="stat-value ${cls(alpha)}">${fmt1(alpha)}</div>
                ${badgeHtml}
            </div>
        </div>`;

    // ── Chart ───────────────────────────────────────────────────────────────
    const planReturnPct = typeof user.plan_projected_return_pct === 'number' ? user.plan_projected_return_pct : null;
    const planLabel = planReturnPct !== null ? ` · Plan assumes ${planReturnPct.toFixed(1)}%/yr` : '';
    const chartHtml = `
        <div class="benchmark-chart-title">
            Normalized Growth — ${year} &nbsp;(Base = $100${planLabel})
        </div>
        <div class="benchmark-chart-wrapper">
            <canvas id="${canvasId}"></canvas>
        </div>`;

    // ── Allocation breakdown tables ─────────────────────────────────────────
    const userDetails  = user.ticker_details  || [];
    const bogDetails   = bog.ticker_details   || [];
    const f2060Details = f2060.ticker_details || [];

    function allocRows(details, barClass) {
        const isUser = barClass === '';
        return details.map(d => {
            const ret    = d.return_pct;
            const retStr = (ret !== null && ret !== undefined) ? `${ret >= 0 ? '+' : ''}${ret.toFixed(2)}%` : '—';
            const retCls = ret > 0 ? 'positive' : ret < 0 ? 'negative' : '';
            const weight = d.weight * 100;
            const ticker = isUser ? (d.proxy || d.ticker) : (d.ticker || d.proxy);
            const origNote = isUser && d.original && d.original !== d.proxy
                ? `<span style="font-size:0.64rem;color:#aaa;display:block">(holds ${d.original})</span>`
                : '';
            return `<tr>
                <td>
                    <span class="alloc-weight-bar ${barClass}" style="width:${Math.round(weight * 0.8)}px"></span>
                    <strong>${ticker}</strong>${origNote}
                </td>
                <td>${d.desc || '—'}</td>
                <td style="text-align:right">${weight.toFixed(1)}%</td>
                <td style="text-align:right" class="${retCls}">${retStr}</td>
            </tr>`;
        }).join('');
    }

    const allocHtml = `
        <div class="benchmark-alloc-grid">
            <div class="alloc-block">
                <div class="alloc-block-header user-header">${username}'s Allocation (proxy ETFs)</div>
                <table>
                    <thead><tr>
                        <th>ETF</th>
                        <th>Description</th>
                        <th style="text-align:right">Weight</th>
                        <th style="text-align:right">${year} Return</th>
                    </tr></thead>
                    <tbody>${allocRows(userDetails, '')}</tbody>
                </table>
            </div>
            <div class="alloc-block bog-block">
                <div class="alloc-block-header bog-header">Boglehead 3-Fund Portfolio</div>
                <table>
                    <thead><tr>
                        <th>ETF</th>
                        <th>Description</th>
                        <th style="text-align:right">Weight</th>
                        <th style="text-align:right">${year} Return</th>
                    </tr></thead>
                    <tbody>${allocRows(bogDetails, 'bog')}</tbody>
                </table>
            </div>
        </div>`;

    const footnoteHtml = `
        <p class="benchmark-footnote">
            Data: ${data.data_source || 'Yahoo Finance'} ·
            Prices adjusted for dividends &amp; splits ·
            User allocation uses proxy ETFs for funds without public price history ·
            Assumes constant weighting throughout the full calendar year ${year}
        </p>`;

    panelInner.innerHTML = statsHtml + chartHtml + allocHtml + footnoteHtml;

    // ── Draw Chart.js chart ─────────────────────────────────────────────────
    const canvas = document.getElementById(canvasId);
    if (!canvas || !window.Chart) return;

    if (_benchmarkCharts[cacheKey]) {
        try { _benchmarkCharts[cacheKey].destroy(); } catch (_) {}
    }

    const months    = data.months || ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const userNorm  = (user.normalized  || []).map(v => (v !== null && v !== undefined) ? v : null);
    const bogNorm   = (bog.normalized   || []).map(v => (v !== null && v !== undefined) ? v : null);
    const f2060Norm = (f2060.normalized || []).map(v => (v !== null && v !== undefined) ? v : null);

    // 13 points across 13 ticks: ['Jan','Feb',...,'Dec','']
    // Each tick = start of that month. Data at each tick = portfolio value at that moment.
    // Jan (pos 0) = Jan 1 baseline ($100). Feb (pos 1) = end-of-Jan close. Etc.
    // Blank '' (pos 12) = Dec 31 close — so the Dec→blank segment shows December's return.
    const labels    = [...months, ''];
    const userData  = [100, ...userNorm];
    const bogData   = [100, ...bogNorm];
    const f2060Data = [100, ...f2060Norm];

    // ── Projected "line of fit" ─────────────────────────────────────────────
    // 13 points matching labels: $100 at Jan 1, compound monthly growth through Dec 31.
    const projectedFitData = planReturnPct !== null
        ? [100, ...months.map((_, i) => {
              const monthlyRate = Math.pow(1 + planReturnPct / 100, 1 / 12) - 1;
              return parseFloat((100 * Math.pow(1 + monthlyRate, i + 1)).toFixed(4));
          })]
        : null;

    _benchmarkCharts[cacheKey] = new Chart(canvas, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label:            user.label || `${username}'s Portfolio`,
                    data:             userData,
                    borderColor:      '#1F3A8A',
                    backgroundColor:  'rgba(31,58,138,0.08)',
                    borderWidth:      2.5,
                    pointRadius:      3,
                    pointHoverRadius: 5,
                    tension:          0.3,
                    fill:             true,
                    spanGaps:         true,
                },
                {
                    label:            bog.label || 'Boglehead 3-Fund',
                    data:             bogData,
                    borderColor:      '#C8A44D',
                    backgroundColor:  'rgba(200,164,77,0.07)',
                    borderWidth:      2.5,
                    borderDash:       [5, 3],
                    pointRadius:      3,
                    pointHoverRadius: 5,
                    tension:          0.3,
                    fill:             true,
                    spanGaps:         true,
                },
                {
                    label:            f2060.label || 'Fidelity Freedom 2060',
                    data:             f2060Data,
                    borderColor:      '#0D9488',
                    backgroundColor:  'rgba(13,148,136,0.06)',
                    borderWidth:      2.5,
                    borderDash:       [3, 3],
                    pointRadius:      3,
                    pointHoverRadius: 5,
                    tension:          0.3,
                    fill:             true,
                    spanGaps:         true,
                },
                ...(projectedFitData ? [{
                    label:            planReturnPct !== null
                                          ? `Plan Projected (${planReturnPct.toFixed(1)}%/yr)`
                                          : 'Plan Projected Return',
                    data:             projectedFitData,
                    borderColor:      '#9333EA',
                    backgroundColor:  'transparent',
                    borderWidth:      1.5,
                    borderDash:       [6, 4],
                    pointRadius:      0,
                    pointHoverRadius: 3,
                    tension:          0,
                    fill:             false,
                    spanGaps:         true,
                }] : []),
            ],
        },
        options: {
            responsive:          true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        font:     { size: 11, family: 'Montserrat, sans-serif' },
                        boxWidth: 14,
                        padding:  16,
                    },
                },
                tooltip: {
                    callbacks: {
                        title: ctx => `${ctx[0].label} ${year}`,
                        label: ctx => {
                            const v = ctx.parsed.y;
                            if (v === null || v === undefined) return `${ctx.dataset.label}: —`;
                            const change = v - 100;
                            const sign   = change >= 0 ? '+' : '';
                            return `${ctx.dataset.label}: $${v.toFixed(2)}  (${sign}${change.toFixed(2)}%)`;
                        },
                    },
                    backgroundColor: 'rgba(15,30,61,0.88)',
                    titleColor:      '#C8A44D',
                    bodyColor:       '#F8F5EE',
                    padding:         10,
                    cornerRadius:    6,
                },
            },
            scales: {
                x: {
                    grid:   { color: 'rgba(0,0,0,0.04)' },
                    ticks:  { font: { size: 10 }, color: '#6A7791' },
                },
                y: {
                    grid: { color: 'rgba(0,0,0,0.06)' },
                    ticks: {
                        font:     { size: 10 },
                        color:    '#6A7791',
                        callback: v => `$${v.toFixed(0)}`,
                    },
                    title: {
                        display: true,
                        text:    'Growth of $100 invested Jan 1',
                        color:   '#6A7791',
                        font:    { size: 10 },
                    },
                },
            },
        },
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
    const housingAssets = result.assumptions?.housing_assets || {};
    const housingAssetList = Array.isArray(housingAssets.assets) ? housingAssets.assets : [];
    const rentalCashflow = housingAssets.cashflow_treatment || {};
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
    const housingAssetRows = housingAssetList.map((asset) => {
        const participantNames = Array.isArray(asset.participants) && asset.participants.length
            ? asset.participants.join(' + ')
            : '—';
        const homeValue = Number(asset.current_home_value || 0);
        const loanBalance = Number(asset.loan_balance || 0);
        const currentEquity = Number(
            asset.current_equity !== undefined
                ? asset.current_equity
                : Math.max(homeValue - loanBalance, 0)
        );
        const monthlyPayment = Number(asset.monthly_payment || 0);
        const monthlyEscrow = Number(asset.monthly_escrow || 0);
        const convertAfterYears = Number(asset.convert_to_rental_after_years || 0);
        const monthlyRentPremium = Number(
            asset.rental_monthly_premium_over_p_and_i
            ?? asset.monthly_rent_premium
            ?? 0
        );
        const vacancyRate = Number(asset.vacancy_rate || 0);
        const maintenanceRate = Number(asset.maintenance_rate || 0);
        const appreciationRate = Number(
            asset.annual_appreciation_rate
            ?? asset.conservative_annual_appreciation_rate
            ?? 0
        );

        return `
            <tr>
                <td><strong>${asset.name || 'Property'}</strong></td>
                <td>${participantNames}</td>
                <td>${formatCurrency(homeValue)}</td>
                <td>${formatCurrency(loanBalance)}</td>
                <td>${formatCurrency(currentEquity)}</td>
                <td>${formatCurrency(monthlyPayment)}</td>
                <td>${formatCurrency(monthlyEscrow)}</td>
                <td>${convertAfterYears} yrs</td>
                <td>${formatCurrency(monthlyRentPremium)}</td>
                <td>${(vacancyRate * 100).toFixed(1)}%</td>
                <td>${(maintenanceRate * 100).toFixed(1)}%</td>
                <td>${(appreciationRate * 100).toFixed(1)}%</td>
                <td>${asset.include_in_individual_analysis ? 'Yes' : 'No'}</td>
            </tr>`;
    }).join('');

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

                <div class="assumptions-grid assumptions-grid--stress">
                    <div class="assumptions-group">
                        <div class="assumptions-group-title">Timeline</div>
                        ${horizon.current_age !== undefined ? `<div class="assump-row"><span>Current Age</span><span>${horizon.current_age}</span></div>` : ''}
                        ${horizon.retirement_age !== undefined ? `<div class="assump-row"><span>Retirement Age</span><span>${horizon.retirement_age}</span></div>` : ''}
                        <div class="assump-row"><span>Life Expectancy</span><span>${horizon.life_expectancy_age || 95}</span></div>
                        <div class="assump-row"><span>Years Simulated</span><span>${horizon.years_simulated || '—'}</span></div>
                    </div>

                    <div class="assumptions-group">
                        <div class="assumptions-group-title">Portfolio Snapshot</div>
                        ${portfolio.starting_total_balance !== undefined ? `<div class="assump-row"><span>Starting Balance (Stress Baseline)</span><span>${formatCurrency(portfolio.starting_total_balance)}</span></div>` : ''}
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

                    <div class="assumptions-group assumptions-group--row2-col2">
                        <div class="assumptions-group-title">Return Model</div>
                        <div class="assump-row"><span>Distribution</span><span class="assump-note">Lognormal w/ Student-t shocks (df=7)</span></div>
                        <div class="assump-row"><span>Downside Skew</span><span>${model.downside_skew_multiplier || 1.15}× amplification</span></div>
                        <div class="assump-row"><span>Volatility Clustering</span><span class="assump-note">GARCH-like (ω=0.08, α=0.17, β=0.78)</span></div>
                        <div class="assump-row"><span>Simulations</span><span>${(result.simulation_count || 10000).toLocaleString()}</span></div>
                    </div>

                    <div class="assumptions-group assumptions-group--row2-col3">
                        <div class="assumptions-group-title">Retirement Outcome Percentiles</div>
                        <div class="assump-row"><span>P10 (Pessimistic)</span><span>${formatCurrency(retirementP10)}</span></div>
                        <div class="assump-row"><span>P50 (Median)</span><span>${formatCurrency(retirementP50)}</span></div>
                        <div class="assump-row"><span>P90 (Optimistic)</span><span>${formatCurrency(retirementP90)}</span></div>
                    </div>

                    <div class="assumptions-group assumptions-group--row2-col4">
                        <div class="assumptions-group-title">Life Outcome Percentiles</div>
                        <div class="assump-row"><span>P10 (Pessimistic)</span><span>${formatCurrency(lifeP10)}</span></div>
                        <div class="assump-row"><span>P50 (Median)</span><span>${formatCurrency(lifeP50)}</span></div>
                        <div class="assump-row"><span>P90 (Optimistic)</span><span>${formatCurrency(lifeP90)}</span></div>
                    </div>
                </div>

                <div style="height: 12px;"></div>
                <div class="assumptions-group assumptions-group--housing" style="margin-top: 0 !important;">
                    <div class="assumptions-group-title">Housing / Rental</div>
                    <div class="assump-row"><span>Enabled</span><span>${housingAssets.enabled ? 'Yes' : 'No'}</span></div>
                    <div class="assump-row"><span>Properties Modeled</span><span>${housingAssetList.length}</span></div>
                    ${housingAssets.counting_rule ? `<div class="assump-row"><span>Count Rule</span><span class="assump-note">${housingAssets.counting_rule}</span></div>` : ''}
                    <div class="assump-row"><span>Pre-Retirement</span><span class="assump-note">${rentalCashflow.pre_retirement || 'Net rent is added to investable annual contributions before retirement.'}</span></div>
                    <div class="assump-row"><span>Post-Retirement</span><span class="assump-note">${rentalCashflow.post_retirement || 'Net rent offsets retirement withdrawals before the portfolio is tapped.'}</span></div>
                    <div class="assump-row"><span>Rent Basis</span><span class="assump-note">${rentalCashflow.rent_basis || 'Monthly rent starts at principal + interest plus rental premium and grows with inflation after conversion.'}</span></div>
                    <div class="assump-row"><span>Net Cashflow</span><span class="assump-note">${rentalCashflow.net_cashflow_formula || 'Gross rent less vacancy, maintenance, and annual mortgage principal + interest.'}</span></div>
                    <div class="assump-row"><span>Escrow Treatment</span><span class="assump-note">${rentalCashflow.escrow_treatment || 'Escrow is not included in the Monte Carlo rental cashflow formula.'}</span></div>
                    <div class="assump-row"><span>Equity Treatment</span><span class="assump-note">${rentalCashflow.equity_treatment || housingAssets.treatment || 'Housing equity is included in terminal net worth.'}</span></div>
                    ${housingAssetList.length > 0 ? `
                    <div class="assumptions-table-wrap">
                        <table class="assumptions-table">
                            <thead><tr>
                                <th>Name</th><th>Participants</th><th>Home Value</th><th>Loan Balance</th><th>Equity</th>
                                <th>P&amp;I /mo</th><th>Escrow /mo</th><th>Convert After</th><th>Rent Premium</th>
                                <th>Vacancy</th><th>Maint.</th><th>Apprec.</th><th>Shown Individually</th>
                            </tr></thead>
                            <tbody>${housingAssetRows}</tbody>
                        </table>
                    </div>` : ''}
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
    // Populate comparison-year dropdown from projection horizon
    const yearSelect = document.getElementById('year');
    while (yearSelect.children.length > 1) {
        yearSelect.removeChild(yearSelect.lastChild());
    }

    const projectedYears = (currentSingleUserData?.projected || [])
        .map((point) => Number(point?.year))
        .filter((year) => Number.isFinite(year) && year > 0);

    const currentYear = new Date().getFullYear();
    const startYear = projectedYears.length > 0
        ? Math.max(1900, Math.min(...projectedYears) - 1)
        : (currentYear - 2);
    const endYear = projectedYears.length > 0
        ? Math.max(...projectedYears)
        : 2090;
    const defaultYear = Math.min(Math.max(currentYear - 1, startYear), endYear);

    for (let year = startYear; year <= endYear; year++) {
        const option = document.createElement('option');
        option.value = year;
        option.textContent = year;
        if (year === defaultYear) {
            option.selected = true;
        }
        yearSelect.appendChild(option);
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
    const comparisonYear = parseInt(document.getElementById('year').value);
    const storedYear = comparisonYear + 1;
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
            console.log(`Submitting 401k balance: ${balance401k} for comparison year ${comparisonYear} (stored year ${storedYear})`);
            const response401k = await fetch(`/api/balances/${username}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    account_type: '401k',
                    year: storedYear,
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
            console.log(`Submitting IRA balance: ${balanceIRA} for comparison year ${comparisonYear} (stored year ${storedYear})`);
            const responseIRA = await fetch(`/api/balances/${username}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    account_type: 'roth_ira',
                    year: storedYear,
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
    window.onDeductionRateChange = onDeductionRateChange;
    window.onStandardDeductionToggleChange = onStandardDeductionToggleChange;
    window.toggleBenchmarkRow = toggleBenchmarkRow;
}
