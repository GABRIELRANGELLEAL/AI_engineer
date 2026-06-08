# API Quick Reference - Executor Agent

## Complete Workflow

```
1. Upload files       → POST /upload
2. Create task        → POST /tasks
3. Plan conversation  → POST /tasks/{id}/message (iterate until plan ready)
4. Approve plan       → POST /tasks/{id}/proceed
5. Start execution    → POST /tasks/{id}/execute/start
6. Execute steps      → POST /tasks/{id}/execute/step (one at a time)
7. Check status       → GET /tasks/{id}/execute/status
```

## Endpoints

### Upload Files
```bash
curl -X POST http://localhost:8000/upload \
  -F "files=@data.csv"
```

### Create Task
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Analyze sales trends in my CSV data",
    "data_source_type": "csv",
    "data_source_meta": {"csv_path": "data.csv"}
  }'
```

### Send Planning Message
```bash
curl -X POST http://localhost:8000/tasks/{task_id}/message \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Yes, please analyze monthly trends"
  }'
```

### Approve Plan
```bash
curl -X POST http://localhost:8000/tasks/{task_id}/proceed
```

### Start Execution
```bash
curl -X POST http://localhost:8000/tasks/{task_id}/execute/start \
  -H "Content-Type: application/json" \
  -d '{
    "output_name": "sales_analysis"
  }'
```

### Execute Step
```bash
curl -X POST http://localhost:8000/tasks/{task_id}/execute/step \
  -H "Content-Type: application/json" \
  -d '{
    "step_number": 1
  }'
```

### Get Execution Status
```bash
curl -X GET http://localhost:8000/tasks/{task_id}/execute/status
```

## Response Examples

### Start Execution Response
```json
{
  "status": "ok",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_status": "executing",
  "total_steps": 5,
  "execution_state": {
    "output_name": "sales_analysis",
    "steps": [
      {
        "description": "Load and validate CSV data",
        "skill_needed": false,
        "arg": null
      },
      {
        "description": "Analyze time series characteristics",
        "skill_needed": true,
        "arg": "C:/Users/.../skills/analyzing-time-series/SKILL.md"
      }
    ],
    "current_step": 0,
    "completed_steps": []
  }
}
```

### Execute Step Response
```json
{
  "status": "ok",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_status": "executing",
  "execution_result": {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "step_number": 1,
    "total_steps": 5,
    "step_description": "Load and validate CSV data",
    "status": "completed",
    "summary": "Successfully loaded CSV with 1000 rows and 2 columns (date, sales). No missing values detected.",
    "generated_files": [
      "sales_analysis_1_validation.json",
      "sales_analysis_1_summary.txt"
    ],
    "all_artifacts": {
      "1": [
        "outputs/550e8400.../step_1/sales_analysis_1_validation.json",
        "outputs/550e8400.../step_1/sales_analysis_1_summary.txt"
      ]
    },
    "next_step_ready": true,
    "tool_uses_count": 4,
    "input_tokens": 1543,
    "output_tokens": 324
  }
}
```

## Error Codes

- `400` - Bad request (invalid step number, wrong status, etc.)
- `404` - Task not found
- `500` - Execution error

## Status Values

- `planning` - Still in planning phase
- `proceeded` - Plan approved, ready to start execution
- `executing` - Currently executing steps
- `completed` - All steps completed successfully
- `failed` - Execution failed

## File Paths

All generated files are saved to:
```
workspace/outputs/{task_id}/step_{n}/{output_name}_{n}_filename.ext
```

To read a generated file:
```bash
curl -X GET http://localhost:8000/files/outputs/{task_id}/step_1/{filename}
```
(Note: File serving endpoint may need to be implemented)

## Testing

Use the test notebook:
```bash
jupyter notebook tests/test_agent.ipynb
```

Or test via Python:
```python
import requests

# Create task
response = requests.post("http://localhost:8000/tasks", json={
    "prompt": "Analyze my sales data",
    "data_source_type": "csv",
    "data_source_meta": {"csv_path": "sales.csv"}
})
task_id = response.json()["task_id"]

# ... planning conversation ...

# Start execution
requests.post(f"http://localhost:8000/tasks/{task_id}/execute/start", json={
    "output_name": "analysis"
})

# Execute step 1
result = requests.post(f"http://localhost:8000/tasks/{task_id}/execute/step", json={
    "step_number": 1
})
print(result.json())
```
