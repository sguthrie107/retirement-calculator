# Retirement Calculator - Web Dashboard

Transform the CLI-based retirement calculator into a production-ready web application for tracking and comparing projected vs. actual retirement performance.

## Features

- **Projection Engine**: Unchanged calculation logic from CLI app
- **Visual Dashboard**: Chart.js graphs showing projected vs actual balances
- **Balance Tracking**: Manual entry of year-end account balances (401k, Roth IRA)
- **Performance Comparison**: Delta calculation showing $ and % differences
- **Multi-User Support**: Ready for multiple users (auth not yet implemented)

## Architecture

```
app/
├── main.py              # FastAPI application factory
├── config.py            # Environment configuration
├── database.py          # SQLAlchemy setup
├── models.py            # Database models (User, Account, ActualBalance)
├── schemas.py           # Pydantic request/response models
├── routes/              # API endpoints
│   ├── dashboard.py     # Main dashboard view
│   ├── projections.py   # Projection API
│   └── balances.py      # Balance CRUD operations
├── services/            # Business logic
│   ├── projection.py    # Wraps lib/ calculation engine
│   └── comparison.py    # Merges actual vs projected data
├── templates/           # Jinja2 HTML templates
└── static/              # CSS and JavaScript

lib/                     # UNCHANGED - calculation engine
data/                    # UNCHANGED - JSON fund data
calculate.py             # UNCHANGED - CLI still works
```

## Setup

### 1. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 2. Configure Environment

```powershell
# Copy example environment file
copy .env.example .env

# Edit .env and set your values (especially SECRET_KEY in production)
```

### 3. Initialize Database

The database is automatically initialized on first run. Users from `data/users.json` can be used immediately.

### 4. Run the Application

```powershell
# Development mode (with auto-reload)
uvicorn app.main:app --reload --port 8000

# Production mode
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open your browser to: **http://localhost:8000**

## Usage

### Dashboard

1. Select a user from the dropdown (Steven or Alyssa from users.json)
2. View projected balance graph based on existing calculation logic
3. Add actual year-end balances using "➕ Add Actual Balance" button
4. Compare projected vs actual in the performance comparison table

### Adding Actual Balances

1. Click "➕ Add Actual Balance"
2. Select account type (401k or Roth IRA)
3. Enter year and balance
4. Optional: Add notes
5. Submit to see updated comparison

### API Endpoints

- `GET /` - Dashboard UI
- `GET /api/comparison/{username}` - Get projected vs actual data (JSON)
- `POST /api/balances/{username}` - Create new balance entry
- `GET /api/balances/{username}` - List all balances for user
- `PUT /api/balances/{balance_id}` - Update existing balance
- `DELETE /api/balances/{balance_id}` - Delete balance entry

API documentation available at: **http://localhost:8000/docs**

## CLI Still Works

The original CLI calculator is unchanged:

```powershell
python calculate.py
```

Both entry points share the same calculation engine in `lib/`.

## Database Schema

### Users
- `id`: Primary key
- `name`: Unique username
- `created_at`: Timestamp

### Accounts
- `id`: Primary key
- `user_id`: Foreign key to users
- `account_type`: '401k' or 'roth_ira'
- `provider`: Optional (Fidelity, Vanguard)
- UNIQUE constraint on (user_id, account_type)

### Actual Balances
- `id`: Primary key
- `account_id`: Foreign key to accounts
- `year`: Integer (2000-2100)
- `balance`: Float (>= 0)
- `notes`: Optional text
- `recorded_at`: Timestamp
- UNIQUE constraint on (account_id, year) - prevents duplicate entries

## Security Features

- ✅ Input validation (Pydantic schemas)
- ✅ SQL injection protection (SQLAlchemy ORM)
- ✅ UNIQUE constraints prevent data corruption
- ✅ Environment-based configuration
- ✅ CORS restrictions
- ⏳ HTTPS ready (run behind reverse proxy)
- ⏳ Authentication (prepared but not implemented)

## Deployment

### Local Development
```powershell
uvicorn app.main:app --reload
```

### Production (with Gunicorn + Uvicorn workers)
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Implementation Status

✅ **Phase 1** - Core Dashboard
- SQLite database with SQLAlchemy models
- FastAPI application with Jinja2 templates
- Chart.js visualization of projected data
- API route calling existing lib/ engine
- CLI unchanged and functional

✅ **Phase 2** - Actual Balance Tracking
- Balance entry form with validation
- POST/PUT/DELETE balance routes
- Actual vs projected overlay on graph
- Delta table showing year-by-year differences
- Auto-create users/accounts as needed

⏳ **Phase 3** - Polish & Deploy (Future)
- Dockerfile for containerization
- Advanced error handling
- Mobile-responsive improvements
- Projection caching (optional performance optimization)
- User authentication system

## Troubleshooting

**"No users found" in dropdown**
- User records are created automatically when you add a balance
- Or manually insert: `INSERT INTO users (name) VALUES ('YourName');`

**Chart not loading**
- Check browser console for errors
- Verify API endpoint returns data: `http://localhost:8000/api/comparison/Steven`
- Ensure user exists in `data/users.json`

**"Balance already exists" error**
- The database prevents duplicate entries for the same account/year
- Use PUT endpoint to update existing balances
- Or delete the old entry first

## Technology Stack

- **Backend**: FastAPI 0.104+, Python 3.11+
- **Database**: SQLite (via SQLAlchemy 2.0+)
- **Frontend**: Vanilla JavaScript, Chart.js 4.4
- **Templating**: Jinja2
- **Calculation Engine**: Existing pandas/numpy-based projections

## License

Same as original retirement-calculator project.
