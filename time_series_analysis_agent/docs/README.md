# Time Series Analysis Agent

A full-stack application for time series analysis powered by AI agents. The system features a FastAPI backend with multi-agent architecture and a modern React frontend for interactive analysis.

## Features

- **Multi-Agent Architecture**: Planner, Translator, and Executor agents work together
- **Flexible Data Sources**: Support for CSV files and database connections
- **Interactive Chat Interface**: Conversational planning with the planner agent
- **Real-time Results**: View analysis plans and agent responses in real-time
- **Modern UI**: Clean, responsive interface built with React and Tailwind CSS

## Architecture

### Backend (FastAPI)
- **Planner Agent**: Analyzes user requests and creates execution plans
- **Translator Agent**: Converts plans into executable code
- **Executor Agent**: Runs analysis and generates results
- **Database**: PostgreSQL for task management and interaction logging

### Frontend (React + TypeScript)
- **Data Source Selector**: Initial screen to choose CSV or Database
- **Chat Interface**: Conversational UI for interacting with the planner agent
- **Results Panel**: Real-time display of plans, outputs, and visualizations

## Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL database
- OpenAI API key (or compatible LLM API)

### Backend Setup

1. **Create virtual environment:**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   # source .venv/bin/activate  # Linux/Mac
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables:**
   Create a `.env` file in the root directory:
   ```env
   DATABASE_URL=postgresql://user:password@localhost:5432/dbname
   OPENAI_API_KEY=your_api_key_here
   ```

4. **Run the backend:**
   ```bash
   python main.py
   ```
   The API will be available at `http://localhost:8000`

### Frontend Setup

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Run the development server:**
   ```bash
   npm run dev
   ```
   The frontend will be available at `http://localhost:3000`

3. **Build for production:**
   ```bash
   npm run build
   npm run preview
   ```

## Usage

### Starting a New Analysis

1. **Launch the application** and navigate to `http://localhost:3000`

2. **Select your data source:**
   - **CSV**: Provide the path to your CSV file
   - **Database**: Provide your database ID

3. **Describe your analysis:**
   Enter your initial prompt describing what you want to analyze
   Example: "I want to analyze sales trends and forecast the next quarter"

4. **Interact with the planner:**
   - Ask questions about the analysis
   - Refine the plan
   - Request changes or clarifications

5. **View results:**
   - See the analysis plan in the results panel
   - View agent responses as they come in
   - Track the conversation history in the chat

### API Endpoints

- `POST /tasks` - Create a new task
- `POST /tasks/{task_id}/messages` - Send a message to continue conversation
- `GET /tasks/{task_id}` - Get task details
- `GET /tasks/{task_id}/interactions` - Get all interactions
- `POST /tasks/{task_id}/proceed` - Mark task as ready for execution

## Project Structure

```
time_series_analysis_agent/
├── agents/                    # Agent implementations
│   ├── planner_agent.py
│   ├── translator_agent.py
│   └── executor_agent.py
├── src/                       # Frontend source
│   ├── components/
│   │   ├── DataSourceSelector.tsx
│   │   ├── AnalysisWorkspace.tsx
│   │   ├── ChatInterface.tsx
│   │   └── ResultsPanel.tsx
│   ├── api.ts                # API client
│   ├── types.ts              # TypeScript types
│   ├── App.tsx               # Main app component
│   └── main.tsx              # Entry point
├── tests/                     # Tests
├── main.py                    # FastAPI backend entry point
├── requirements.txt           # Python dependencies
├── package.json               # Node.js dependencies
└── vite.config.ts            # Vite configuration
```

## Technologies

### Backend
- **FastAPI**: Modern, fast web framework
- **SQLAlchemy**: SQL toolkit and ORM
- **PostgreSQL**: Relational database
- **LangChain**: LLM orchestration
- **OpenAI**: Language model API

### Frontend
- **React 18**: UI library
- **TypeScript**: Type-safe JavaScript
- **Vite**: Fast build tool
- **Tailwind CSS**: Utility-first CSS framework
- **Axios**: HTTP client
- **React Markdown**: Markdown rendering
- **Lucide React**: Icon library

## Development

### Running Tests

```bash
# Backend tests
pytest

# Frontend tests (if configured)
npm test
```

### Linting

```bash
# Frontend linting
npm run lint
```

## Deployment

### Backend Deployment (Heroku example)

1. Create a Heroku app
2. Add PostgreSQL addon
3. Set environment variables
4. Deploy:
   ```bash
   git push heroku main
   ```

### Frontend Deployment (Vercel example)

1. Build the frontend:
   ```bash
   npm run build
   ```

2. Deploy the `dist/` folder to your hosting provider

3. Configure environment variables for API URL

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## License

MIT License - feel free to use this project for your own purposes.

## Support

For issues and questions, please open an issue on GitHub.
