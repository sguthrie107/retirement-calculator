// Chart.js initialization and data management

let chartInstance = null;

// Color palette for multiple users
const userColors = {
    'Steven': { border: '#3b82f6', bg: 'rgba(59, 130, 246, 0.1)' },
    'Alyssa': { border: '#ef4444', bg: 'rgba(239, 68, 68, 0.1)' },
    'User3': { border: '#f59e0b', bg: 'rgba(245, 158, 11, 0.1)' },
    'User4': { border: '#8b5cf6', bg: 'rgba(139, 92, 246, 0.1)' },
};

async function loadUserData() {
    const userSelect = document.getElementById('userSelect').value;
    if (!userSelect) return;
    
    const addBalanceBtn = document.getElementById('addBalanceBtn');
    const deltaTable = document.getElementById('deltaTable');
    
    // Show/hide balance add button and delta table based on selection
    if (userSelect === 'all') {
        addBalanceBtn.style.display = 'none';
        deltaTable.style.display = 'none';
        loadAllUsers();
    } else {
        addBalanceBtn.style.display = 'inline-block';
        deltaTable.style.display = 'block';
        loadSingleUser(userSelect);
    }
}

async function loadSingleUser(username) {
    try {
        const response = await fetch(`/api/comparison/${username}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        renderSingleUserChart(username, data);
        renderDeltaTable(data.deltas);
    } catch (error) {
        console.error('Error loading user data:', error);
        document.getElementById('deltaContent').innerHTML = 
            `<p class="loading" style="color: #ef4444;">Error loading data: ${error.message}</p>`;
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
            `<p class="loading" style="color: #ef4444;">Error loading data: ${error.message}</p>`;
    }
}

function renderSingleUserChart(username, data) {
    const ctx = document.getElementById('retirementChart');
    
    // Destroy existing chart if it exists
    if (chartInstance) {
        chartInstance.destroy();
    }
    
    // Extract years from projected data
    const years = data.projected.map(d => d.year);
    
    // Create actual data array matching projected years (null for missing years)
    const actualByYear = {};
    data.actual.forEach(d => {
        actualByYear[d.year] = d.balance;
    });
    
    const actualData = years.map(year => actualByYear[year] || null);
    
    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: years,
            datasets: [
                {
                    label: `${username} - Projected Balance`,
                    data: data.projected.map(d => d.balance),
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.1,
                    pointRadius: 3,
                    pointHoverRadius: 5,
                },
                {
                    label: `${username} - Actual Balance`,
                    data: actualData,
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 3,
                    borderDash: [5, 5],
                    fill: false,
                    tension: 0.1,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    spanGaps: true,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        font: { size: 14 },
                        padding: 15,
                    }
                },
                tooltip: {
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
                        font: { size: 14, weight: 'bold' }
                    },
                    grid: { color: '#e2e8f0' }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Balance ($)',
                        font: { size: 14, weight: 'bold' }
                    },
                    ticks: {
                        callback: function(value) {
                            return new Intl.NumberFormat('en-US', {
                                style: 'currency',
                                currency: 'USD',
                                minimumFractionDigits: 0,
                            }).format(value);
                        }
                    },
                    grid: { color: '#e2e8f0' }
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
    usersData.forEach(user => {
        user.projected.forEach(d => allYears.add(d.year));
    });
    const years = Array.from(allYears).sort((a, b) => a - b);
    
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
        
        return {
            label: `${user.username} - Projected`,
            data: years.map(year => userBalances[year] || null),
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
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        font: { size: 14 },
                        padding: 15,
                    }
                },
                tooltip: {
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
                        font: { size: 14, weight: 'bold' }
                    },
                    grid: { color: '#e2e8f0' }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Balance ($)',
                        font: { size: 14, weight: 'bold' }
                    },
                    ticks: {
                        callback: function(value) {
                            return new Intl.NumberFormat('en-US', {
                                style: 'currency',
                                currency: 'USD',
                                minimumFractionDigits: 0,
                            }).format(value);
                        }
                    },
                    grid: { color: '#e2e8f0' }
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
    
    let html = '<table><thead><tr>';
    html += '<th>Year</th>';
    html += '<th>Projected</th>';
    html += '<th>Actual</th>';
    html += '<th>Difference ($)</th>';
    html += '<th>Difference (%)</th>';
    html += '</tr></thead><tbody>';
    
    deltas.forEach(delta => {
        const diffClass = delta.delta >= 0 ? 'positive' : 'negative';
        const diffSign = delta.delta >= 0 ? '+' : '';
        
        html += '<tr>';
        html += `<td><strong>${delta.year}</strong></td>`;
        html += `<td>${formatCurrency(delta.projected)}</td>`;
        html += `<td>${formatCurrency(delta.actual)}</td>`;
        html += `<td class="${diffClass}">${diffSign}${formatCurrency(delta.delta)}</td>`;
        html += `<td class="${diffClass}">${diffSign}${delta.delta_pct.toFixed(2)}%</td>`;
        html += '</tr>';
    });
    
    html += '</tbody></table>';
    content.innerHTML = html;
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
    document.getElementById('balanceModal').style.display = 'flex';
}

function hideBalanceForm() {
    document.getElementById('balanceModal').style.display = 'none';
    document.getElementById('balanceForm').reset();
}

async function submitBalance(event) {
    event.preventDefault();
    
    const username = document.getElementById('userSelect').value;
    const accountType = document.getElementById('accountType').value;
    const year = parseInt(document.getElementById('year').value);
    const balance = parseFloat(document.getElementById('balance').value);
    const notes = document.getElementById('notes').value;
    
    const data = {
        account_type: accountType,
        year: year,
        balance: balance,
        notes: notes || null,
    };
    
    try {
        const response = await fetch(`/api/balances/${username}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        
        if (response.status === 409) {
            alert('A balance for this account and year already exists. Please edit the existing entry.');
            return;
        }
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        hideBalanceForm();
        loadUserData(); // Refresh chart and table
        alert('Balance added successfully!');
    } catch (error) {
        console.error('Error submitting balance:', error);
        alert(`Error: ${error.message}`);
    }
}
