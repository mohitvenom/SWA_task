# ForgeAI Frontend

This directory contains the React + TypeScript + Vite frontend for ForgeAI.

## Implementation Details

The frontend has been developed through multiple phases:

- **Phase F1 (Foundation)**: Core React shell, Tailwind styling, component setup.
- **Phase F2 (API Integration)**: Connecting to the FastAPI backend `POST /execute` endpoint.
- **Phase F3 (Visualization)**: Detailed autonomous pipeline visualization and results rendering.
- **Phase F4 (Execution History)**: LocalStorage-backed execution history tracking, allowing users to view, reload, and audit past tasks and their outcomes.

*(Note: WebSockets, database history, and Redux/Zustand are excluded as per architectural requirements.)*

## Requirements
- Node.js (v18 or higher recommended)
- npm or yarn
- Python 3.12+ (for the ForgeAI backend)

## Installation

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```
2. Install dependencies:
   ```bash
   npm install
   ```

## Configuration

The frontend expects the FastAPI backend to be running. By default, it looks for the API at `http://localhost:8000`. 
To change this, create or modify the `.env` file in the `frontend` directory based on `.env.example`:

```env
VITE_API_URL=http://localhost:8000
```

## Running the Application

### 1. Start the Backend

In a separate terminal, from the root of the repository, start the FastAPI server:

```bash
uvicorn src.forgeai.api.main:app --reload
```
*Note: Make sure your environment variables (like LLM keys) are configured in the root `.env`.*

### 2. Start the Frontend

In the `frontend/` directory, run the Vite development server:

```bash
npm run dev
```

The UI will be accessible at [http://localhost:5173](http://localhost:5173).

## Building for Production

To create a production build:

```bash
npm run build
```

## Testing / Linting

To run the linter:
```bash
npm run lint
```
