# Time Series Analysis Agent - Frontend

React + TypeScript frontend for the Time Series Analysis Agent.

## Quick Start

### Development (local)

```bash
npm install
npm run dev
```

Open http://localhost:3000

### Docker (recommended)

From project root:

```bash
docker compose up --build
```

The frontend service will install dependencies and start automatically.

## Features

- **Dark-themed source selection** (Page 1)
- **Multi-file CSV upload** with drag-and-drop
- **Real-time chat** with planner agent
- **Results panel** with plans and outputs
- **Database support** (coming soon)

## Tech Stack

- React 18
- TypeScript
- Vite
- Tailwind CSS
- Axios
- React Markdown
- Lucide React (icons)

## API Integration

The frontend proxies `/api/*` requests to the backend at `http://localhost:8000` (dev) or `http://api:8000` (Docker).

See `vite.config.ts` for proxy configuration.

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── DataSourceSelector.tsx    # Page 1: Dark source picker
│   │   ├── WorkspacePage.tsx          # Page 2: Main workspace
│   │   ├── FileUploadZone.tsx         # CSV upload UI
│   │   ├── ChatInterface.tsx          # Chat with planner
│   │   └── ResultsPanel.tsx           # Plans & outputs
│   ├── api.ts                         # API client
│   ├── types.ts                       # TypeScript types
│   ├── App.tsx                        # Main app component
│   └── main.tsx                       # Entry point
├── package.json
├── vite.config.ts
└── tailwind.config.js
```

## Development

- Hot reload enabled (save files to see changes)
- TypeScript strict mode
- ESLint configured
- Tailwind CSS for styling

## Build

```bash
npm run build
```

Output: `dist/` folder

## Environment

- `VITE_API_PROXY_TARGET` - API URL (used in Docker)
