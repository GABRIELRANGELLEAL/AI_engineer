# Time Series Analysis Agent

A multi-agent system for analyzing time series data using Claude AI and specialized skills with **interactive visual results**.

## 🎯 Key Features

- ✅ **Interactive Analytics UI** - Each step generates text narratives + tables + Plotly charts
- ✅ **Step-by-step execution** with user approval between steps
- ✅ **Multi-agent architecture** (Planner → Helper → Executor)
- ✅ **Skill-based system** for specialized tasks
- ✅ **PostgreSQL logging** for full audit trail
- ✅ **Conversation-based planning** with file discovery
- ✅ **Tool access** for reading, writing, and running code

## 🚀 Quick Start

### Prerequisites

```bash
# Python 3.10+
pip install anthropic sqlalchemy psycopg2-binary fastapi uvicorn python-dotenv pandas plotly

# Node.js 18+
cd frontend
npm install
```

### Environment Setup

Create `.env`:
```env
ANTHROPIC_API_KEY=your_key_here
DATABASE_URL=postgresql://user:pass@host:port/dbname
```

### Run

```bash
# Backend
python main.py
# → http://localhost:8000

# Frontend (new terminal)
cd frontend
npm run dev
# → http://localhost:3000
```

## 📊 How It Works

### 1. Upload Data
Upload CSV files with time series data (columns: `date`, `value`)

### 2. Planning
Chat with the planner agent to create an analysis plan:
```
User: "Analyze my sales data for trends and seasonality"
Planner: Creates 7-step plan with exploratory analysis, decomposition, forecasting
```

### 3. Execution
Approve plan → Execute steps one by one with **visual results**

Each step generates:
- 📝 **Narrative text** explaining findings
- 📊 **Tables** with metrics and statistics  
- 📈 **Interactive Plotly charts** (zoom, hover, download)

Example Step 2 output:

```
Step 2: Exploratory Analysis ✓

"The time series has 365 daily observations from 2023-01-01 to 2023-12-31.
Mean is 152.3 with std dev of 45.6, indicating moderate variability..."

[Table: Summary Statistics]
| Metric    | Value |
|-----------|-------|
| Mean      | 152.3 |
| Std Dev   | 45.6  |

[Interactive Plotly Chart: Time Series Plot]
[Interactive Plotly Chart: Distribution Histogram]
```

### 4. Results
All steps displayed in sequence with interactive visualizations

## 🏗️ Architecture

```
┌──────────────┐
│ Frontend     │  React + Plotly
│ (Port 3000)  │
└──────┬───────┘
       │ HTTP
┌──────▼───────┐
│ FastAPI      │  Python + Claude
│ (Port 8000)  │
└──────┬───────┘
       │
┌──────▼───────┐
│ PostgreSQL   │  Task state + logs
└──────────────┘

┌──────────────────────────────────┐
│ Workspace                        │
│ ├── uploads/      (CSV inputs)  │
│ └── outputs/      (Results)     │
│     └── {task_id}/               │
│         ├── step_1/              │
│         │   └── *_ui.json        │
│         ├── step_2/              │
│         │   └── *_ui.json        │
│         └── ...                  │
└──────────────────────────────────┘
```

## 🤖 Agents

### 1. Planner Agent
Creates step-by-step plans through conversation
- Tools: `view_file`, `search_files`, `get_file_stats`
- Explores data before planning

### 2. Helper Context Agent
Enriches steps with skill assignments
- Matches steps to available skills
- Returns skill paths for executor

### 3. Executor Agent ⭐
Executes steps with tools and generates UI
- Tools: `read_file`, `write_file`, `run_python`, `list_files`
- Generates `ui.json` per step with blocks:
  - `text` - narrative
  - `table` - structured data
  - `plot` - Plotly specs

## 📁 Project Structure

```
time_series_analysis_agent/
├── agents/
│   ├── planner_agent.py
│   ├── helper_contet_agent.py
│   └── executor_agent.py
├── skills/
│   └── analyzing-time-series/
│       ├── SKILL.md
│       └── scripts/
├── frontend/
│   └── src/
│       ├── components/
│       │   ├── UIBlock.tsx          ⭐ NEW
│       │   ├── StepResultPanel.tsx  ⭐ NEW
│       │   └── ExecutionPanel.tsx   ⭐ NEW
│       └── api.ts
├── workspace/
│   ├── uploads/
│   └── outputs/
├── docs/
│   ├── UI_ANALYTICS_GUIDE.md        ⭐ NEW
│   └── QUICK_SETUP_GUIDE.md         ⭐ NEW
└── main.py
```

## 🔑 Key API Endpoints

```
POST   /uploads/csv              Upload data files
POST   /tasks                    Create task (planning)
POST   /tasks/{id}/messages      Continue conversation
POST   /tasks/{id}/proceed       Approve plan
POST   /tasks/{id}/execute/start Initialize execution
POST   /tasks/{id}/execute/step  Execute specific step
GET    /tasks/{id}/execute/status Check progress
GET    /workspace/files/{path}   ⭐ Fetch generated files
```

## 📖 Documentation

- [UI Analytics Guide](docs/UI_ANALYTICS_GUIDE.md) - Complete visual system docs
- [Quick Setup Guide](docs/QUICK_SETUP_GUIDE.md) - Testing and troubleshooting
- [Executor Agent](docs/EXECUTOR_AGENT.md) - Technical details
- [API Reference](docs/API_QUICK_REFERENCE.md) - Endpoint examples

## 🧪 Testing

```bash
# Backend integration test
python tests/test_executor_integration.py

# Jupyter notebook
jupyter notebook tests/test_agent.ipynb
```

## 💡 Example Workflow

```python
# 1. Upload CSV
POST /uploads/csv → files uploaded

# 2. Create task
POST /tasks {
  "prompt": "Analyze sales trends",
  "data_source_type": "csv",
  "data_source_meta": {"csv_path": "data.csv"}
}

# 3. Planning conversation (optional)
POST /tasks/{id}/messages {"prompt": "Focus on seasonality"}

# 4. Approve
POST /tasks/{id}/proceed

# 5. Start execution
POST /tasks/{id}/execute/start {"output_name": "analysis"}

# 6. Execute steps
POST /tasks/{id}/execute/step {"step_number": 1}
# → Returns summary + generated_files: ["analysis_1_ui.json"]

# 7. Frontend fetches UI
GET /workspace/files/outputs/{task_id}/step_1/analysis_1_ui.json
# → Returns {"blocks": [text, table, plot]}

# 8. Render visualizations
React components render interactive Plotly charts
```

## 🎨 Visual Output Example

Step executes → Backend generates:

```json
{
  "step_number": 2,
  "title": "Exploratory Analysis",
  "blocks": [
    {"type": "text", "content": "Analysis narrative..."},
    {"type": "table", "columns": [...], "rows": [...]},
    {"type": "plot", "library": "plotly", "spec": {...}}
  ]
}
```

Frontend renders → User sees:
```
┌─────────────────────────────────────┐
│ Step 2 ✓ Exploratory Analysis       │
├─────────────────────────────────────┤
│ [Narrative text explaining findings]│
│                                     │
│ [HTML table with statistics]        │
│                                     │
│ [Interactive Plotly chart]          │
│  - Hover to see values              │
│  - Zoom in/out                      │
│  - Pan                              │
│  - Download as PNG                  │
└─────────────────────────────────────┘
```

## 🔧 Tech Stack

**Backend:**
- FastAPI - REST API
- Anthropic Claude - LLM
- SQLAlchemy - Database ORM
- PostgreSQL - Data persistence
- Pandas/Plotly - Data processing

**Frontend:**
- React + TypeScript
- Plotly.js - Interactive charts
- TailwindCSS - Styling
- Vite - Build tool

## 📊 Database Schema

```sql
-- Tasks
CREATE TABLE tasks (
  id VARCHAR PRIMARY KEY,
  prompt TEXT,
  status VARCHAR,  -- planning, proceeded, executing, completed
  data_source_type VARCHAR,
  data_source_meta TEXT,
  result TEXT,  -- JSON with plan + execution_state
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);

-- Audit log
CREATE TABLE llm_interactions (
  id VARCHAR PRIMARY KEY,
  task_id VARCHAR,
  agent VARCHAR,  -- planner, executor_agent_step_N
  prompt TEXT,
  model_answer TEXT,
  input_tokens INTEGER,
  output_tokens INTEGER,
  raw_response JSONB,
  created_at TIMESTAMP
);
```

## 🚦 Status

✅ **Production Ready** - All core features implemented

Recent additions:
- ✅ Visual analytics system (ui.json generation)
- ✅ Interactive Plotly charts
- ✅ Step-by-step execution panel
- ✅ File serving endpoint
- ✅ Complete documentation

## 🤝 Contributing

1. Fork the repository
2. Create feature branch
3. Add tests
4. Update documentation
5. Submit PR

## 📝 License

[Your License Here]

## 🙏 Acknowledgments

Built with:
- Anthropic Claude Sonnet
- React & Plotly
- FastAPI & SQLAlchemy

---

**Ready to analyze time series! 📈✨**

For detailed setup and testing, see [Quick Setup Guide](docs/QUICK_SETUP_GUIDE.md)
