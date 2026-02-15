// Chart.js initialization and data management

let chartInstance = null;
let accountBalancesByYear = {};  // Global variable for tooltip access

// Color palette for multiple users
const userColors = {
    'Steven': { border: '#1E40AF', bg: 'rgba(30, 64, 175, 0.1)' },
    'Alyssa': { border: '#F97316', bg: 'rgba(249, 115, 22, 0.1)' },
    'User3': { border: '#06B6D4', bg: 'rgba(6, 182, 212, 0.1)' },
    'User4': { border: '#8B5CF6', bg: 'rgba(139, 92, 246, 0.1)' },
};

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
    
    // Show/hide balance add button and delta table based on selection
    if (selectedValue === 'all') {
        console.log('Loading all users view');
        addBalanceBtn.style.display = 'none';
        deltaTable.style.display = 'none';
        loadAllUsers();
    } else {
        console.log('Loading single user:', selectedValue);
        addBalanceBtn.style.display = 'inline-block';
        deltaTable.style.display = 'block';
        loadSingleUser(selectedValue);
    }
}

async function loadSingleUser(username) {
    try {
        console.log('loadSingleUser called for:', username);
        const apiUrl = `/api/comparison/${username}`;
        console.log('Fetching from:', apiUrl);
        
        const response = await fetch(apiUrl);
        console.log('API response:', response.status, response.statusText);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log('API response received. Data:', data);
        console.log('Projected data points:', data.projected ? data.projected.length : 'none');
        console.log('Deltas from API:', data.deltas);
        
        renderSingleUserChart(username, data);
        renderDeltaTable(data.deltas);
    } catch (error) {
        console.error('Error loading user data:', error);
        document.getElementById('deltaContent').innerHTML = 
            `<p class="loading" style="color: #F97316;">Error loading data: ${error.message}</p>`;
        document.getElementById('retirementChart').innerHTML =
            `<p class="loading" style="color: #F97316;">Error loading data: ${error.message}</p>`;
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
            `<p class="loading" style="color: #F97316;">Error loading data: ${error.message}</p>`;
    }
}

function renderSingleUserChart(username, data) {
    const ctx = document.getElementById('retirementChart');
    
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
    accountBalancesByYear = {};  // Reset global variable
    
    // Populate from projected data (which now includes merged account_balances)
    data.projected.forEach(d => {
        accountBalancesByYear[d.year] = d.account_balances || {};
    });
    
    // Also populate from actual data if it exists
    data.actual.forEach(d => {
        actualByYear[d.year] = d.balance;
        accountBalancesByYear[d.year] = d.account_balances || {};
    });
    
    console.log('accountBalancesByYear populated:', accountBalancesByYear);
    
    const actualData = years.map(year => actualByYear[year] || null);
    
    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: years,
            datasets: [
                {
                    label: `${username} - Projected Balance`,
                    data: data.projected.map(d => d.balance),
                    borderColor: '#1E40AF',
                    backgroundColor: 'rgba(30, 64, 175, 0.1)',
                    borderWidth: 3,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 8,
                    pointHoverBackgroundColor: '#3B82F6',
                    pointHoverBorderColor: '#FFFFFF',
                    pointHoverBorderWidth: 2,
                },
                {
                    label: `${username} - Actual Balance`,
                    data: actualData,
                    borderColor: '#F97316',
                    backgroundColor: 'rgba(249, 115, 22, 0.1)',
                    borderWidth: 3,
                    fill: false,
                    tension: 0.4,
                    pointRadius: 6,
                    pointHoverRadius: 10,
                    pointBackgroundColor: '#F97316',
                    pointBorderColor: '#FFFFFF',
                    pointBorderWidth: 2,
                    pointHoverBackgroundColor: '#FB923C',
                    pointHoverBorderColor: '#FFFFFF',
                    pointHoverBorderWidth: 2,
                    spanGaps: true,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        color: '#FFFFFF',
                        font: { size: 14, weight: '600' },
                        padding: 20,
                        usePointStyle: true,
                        pointStyle: 'circle',
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(30, 30, 30, 0.95)',
                    titleColor: '#FFFFFF',
                    bodyColor: '#B3B3B3',
                    borderColor: '#2D2D2D',
                    borderWidth: 1,
                    padding: 16,
                    cornerRadius: 12,
                    displayColors: true,
                    titleFont: { size: 14, weight: '700' },
                    bodyFont: { size: 13, weight: '500' },
                    callbacks: {
                        title: function(context) {
                            return 'Year ' + context[0].label;
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
                                    minimumFractionDigits: 0,
                                }).format(context.parsed.y);
                            }
                            return label;
                        },
                        afterLabel: function(context) {
                            // Show account breakdown for BOTH projected (dataset 0) and actual (dataset 1)
                            const year = context.label;
                            const breakdown = accountBalancesByYear[year];
                            
                            if (breakdown && Object.keys(breakdown).length > 0) {
                                let result = [];
                                if (breakdown['401k']) {
                                    result.push('401k: ' + new Intl.NumberFormat('en-US', {
                                        style: 'currency',
                                        currency: 'USD',
                                        minimumFractionDigits: 0,
                                    }).format(breakdown['401k']));
                                }
                                if (breakdown['roth_ira']) {
                                    result.push('IRA: ' + new Intl.NumberFormat('en-US', {
                                        style: 'currency',
                                        currency: 'USD',
                                        minimumFractionDigits: 0,
                                    }).format(breakdown['roth_ira']));
                                }
                                return result.join('\n');
                            }
                            return '';
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
                        font: { size: 12 }
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
                        font: { size: 12 },
                        callback: function(value) {
                            return new Intl.NumberFormat('en-US', {
                                style: 'currency',
                                currency: 'USD',
                                minimumFractionDigits: 0,
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
                    position: 'top',
                    labels: {
                        color: '#FFFFFF',
                        font: { size: 14, weight: '600' },
                        padding: 20,
                        usePointStyle: true,
                        pointStyle: 'circle',
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(30, 30, 30, 0.95)',
                    titleColor: '#FFFFFF',
                    bodyColor: '#B3B3B3',
                    borderColor: '#2D2D2D',
                    borderWidth: 1,
                    padding: 16,
                    cornerRadius: 12,
                    displayColors: true,
                    titleFont: { size: 14, weight: '700' },
                    bodyFont: { size: 13, weight: '500' },
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += new Intl.NumberFormat('en-US', {
                                    style: 'currency',
                                    currency: 'USD',
                                    minimumFractionDigits: 0,
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
                        font: { size: 12 }
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
                                minimumFractionDigits: 0,
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
        minimumFractionDigits: 0,
    }).format(value);
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
