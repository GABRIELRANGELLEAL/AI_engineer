#!/usr/bin/env python3
"""
Context Builder for Executor Agent

Builds structured context packages for code generation:
1. step — current step metadata
2. workspace — file paths (prevents hallucination)
3. data_preview — deterministic CSV preview with pandas
4. previous_steps — compact summary from prior ui.json files
5. plotly_contract — fixed examples (line/bar/subplot)
"""

import json
import pandas as pd
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = BASE_DIR / "workspace"


@dataclass
class ExecutionContextPackage:
    """Complete context package for code generation."""
    step: dict
    workspace: dict
    data_preview: dict
    previous_steps: List[dict]
    plotly_contract: dict
    skill_context: Optional[str] = None
    
    def to_prompt_text(self) -> str:
        """Convert package to formatted prompt sections."""
        sections = []
        
        sections.append("## STEP")
        sections.append(json.dumps(self.step, indent=2, ensure_ascii=False))
        
        sections.append("\n## WORKSPACE PATHS")
        sections.append(json.dumps(self.workspace, indent=2, ensure_ascii=False))
        
        sections.append("\n## DATA PREVIEW")
        sections.append(json.dumps(self.data_preview, indent=2, ensure_ascii=False))
        
        sections.append("\n## PREVIOUS STEPS SUMMARY")
        sections.append(json.dumps(self.previous_steps, indent=2, ensure_ascii=False))
        
        sections.append("\n## UI.JSON CONTRACT (MUST FOLLOW)")
        sections.append(json.dumps(self.plotly_contract, indent=2, ensure_ascii=False))
        
        if self.skill_context:
            sections.append("\n## SKILL CONTEXT")
            sections.append(self.skill_context)
        
        return "\n".join(sections)


def _build_data_preview(csv_paths: List[str], max_rows: int = 5) -> dict:
    """
    Build deterministic preview of CSV files using pandas.
    
    Extracts:
    - Column names + dtypes
    - Row count
    - Null counts
    - Sample rows (first max_rows)
    - Date range (if datetime columns found)
    
    Args:
        csv_paths: List of relative paths from workspace root
        max_rows: Max sample rows to include
        
    Returns:
        dict with 'files' list containing preview of each CSV
    """
    files_preview = []
    
    for csv_path in csv_paths:
        target = WORKSPACE_DIR / csv_path
        
        if not target.exists() or not target.is_file():
            files_preview.append({
                "path": csv_path,
                "error": f"File not found: {csv_path}"
            })
            continue
        
        try:
            # Read CSV
            df = pd.read_csv(target)
            
            # Column metadata
            columns_meta = []
            for col in df.columns:
                sample_val = df[col].dropna().iloc[0] if not df[col].isna().all() else None
                
                # Convert sample to string (handle datetime, numpy types)
                if pd.api.types.is_datetime64_any_dtype(df[col]) and sample_val is not None:
                    sample_str = pd.to_datetime(sample_val).strftime("%Y-%m-%d")
                else:
                    sample_str = str(sample_val) if sample_val is not None else None
                
                columns_meta.append({
                    "name": col,
                    "dtype": str(df[col].dtype),
                    "sample": sample_str
                })
            
            # Null counts
            null_counts = {col: int(df[col].isna().sum()) for col in df.columns}
            
            # Sample rows (convert to dict, handle datetime/numpy)
            sample_rows = []
            for _, row in df.head(max_rows).iterrows():
                row_dict = {}
                for col in df.columns:
                    val = row[col]
                    if pd.isna(val):
                        row_dict[col] = None
                    elif pd.api.types.is_datetime64_any_dtype(df[col]):
                        row_dict[col] = pd.to_datetime(val).strftime("%Y-%m-%d")
                    else:
                        row_dict[col] = val
                sample_rows.append(row_dict)
            
            # Date range (if datetime columns exist)
            date_range = None
            datetime_cols = df.select_dtypes(include=['datetime64']).columns
            if len(datetime_cols) == 0:
                # Try to infer datetime from object columns
                for col in df.select_dtypes(include=['object']).columns:
                    try:
                        df[col] = pd.to_datetime(df[col])
                        datetime_cols = [col]
                        break
                    except (ValueError, TypeError):
                        pass
            
            if len(datetime_cols) > 0:
                date_col = datetime_cols[0]
                date_range = {
                    "column": date_col,
                    "min": df[date_col].min().strftime("%Y-%m-%d"),
                    "max": df[date_col].max().strftime("%Y-%m-%d")
                }
            
            files_preview.append({
                "path": csv_path,
                "row_count": len(df),
                "columns": columns_meta,
                "null_counts": null_counts,
                "date_range": date_range,
                "sample_rows": sample_rows
            })
            
        except Exception as e:
            files_preview.append({
                "path": csv_path,
                "error": f"Failed to read CSV: {str(e)}"
            })
    
    return {"files": files_preview}


def _build_previous_steps_summary(task_id: str, current_step: int) -> List[dict]:
    """
    Build compact summary of previous steps by reading their ui.json files.
    
    Extracts:
    - step_number, title
    - text blocks (concatenated)
    - tables (just column names + row count, not full data)
    - artifacts (paths to generated files)
    
    Does NOT include:
    - Full plot spec (too large)
    - Full table data (just summary)
    
    Args:
        task_id: Task ID
        current_step: Current step number (1-indexed)
        
    Returns:
        List of step summaries
    """
    summaries = []
    outputs_dir = WORKSPACE_DIR / "outputs" / task_id
    
    if not outputs_dir.exists():
        return []
    
    # Read all previous steps (step_1 to step_{current_step - 1})
    for step_num in range(1, current_step):
        step_dir = outputs_dir / f"step_{step_num}"
        
        if not step_dir.exists():
            continue
        
        # Find *_ui.json file
        ui_json_files = list(step_dir.glob("*_ui.json"))
        
        if not ui_json_files:
            continue
        
        ui_json_path = ui_json_files[0]
        
        try:
            with open(ui_json_path, "r", encoding="utf-8") as f:
                ui_data = json.load(f)
            
            # Extract compact summary
            summary = {
                "step_number": ui_data.get("step_number", step_num),
                "title": ui_data.get("title", f"Step {step_num}")
            }
            
            # Concatenate text blocks
            text_blocks = [
                block["content"]
                for block in ui_data.get("blocks", [])
                if block.get("type") == "text"
            ]
            if text_blocks:
                summary["summary"] = " ".join(text_blocks)[:500]  # Max 500 chars
            
            # Table summaries (column names + row count only)
            tables = {}
            for block in ui_data.get("blocks", []):
                if block.get("type") == "table":
                    table_title = block.get("title", "Unnamed table")
                    tables[table_title] = {
                        "columns": block.get("columns", []),
                        "row_count": len(block.get("rows", []))
                    }
            if tables:
                summary["tables"] = tables
            
            # List artifacts (other files in the step directory)
            artifacts = [
                str(f.relative_to(WORKSPACE_DIR))
                for f in step_dir.iterdir()
                if f.is_file() and not f.name.endswith("_ui.json")
            ]
            if artifacts:
                summary["artifacts"] = artifacts
            
            summaries.append(summary)
            
        except Exception as e:
            # Skip failed reads silently
            pass
    
    return summaries


def _build_plotly_contract() -> dict:
    """
    Build fixed Plotly contract with schema and 3 examples.
    
    Returns:
        dict with 'schema' and 'examples'
    """
    return {
        "schema": {
            "description": "UI payload format for rendering in frontend",
            "structure": {
                "step_number": "int",
                "title": "string",
                "blocks": [
                    {
                        "type": "text | table | plot",
                        "content": "string (for text)",
                        "title": "string (for table/plot)",
                        "columns": ["list of column names (for table)"],
                        "rows": [["list of row arrays (for table)"]],
                        "library": "plotly (for plot)",
                        "spec": {
                            "data": "Plotly data array",
                            "layout": "Plotly layout dict"
                        }
                    }
                ]
            }
        },
        "examples": [
            {
                "name": "Line chart with plotly.express",
                "description": "Simplest way for time series",
                "code": """import plotly.express as px
                    import json

                    fig = px.line(df, x="data", y="vendas", title="Série temporal")
                    spec = json.loads(fig.to_json())

                    block = {
                        "type": "plot",
                        "title": "Série temporal",
                        "library": "plotly",
                        "spec": {
                            "data": spec["data"],
                            "layout": spec["layout"]
                        }
                    }
                """
            },
            {
                "name": "Bar chart with plotly.express",
                "description": "For categorical data",
                "code": """import plotly.express as px
                    import json

                    fig = px.bar(df, x="categoria", y="valor", title="Vendas por categoria")
                    spec = json.loads(fig.to_json())

                    block = {
                        "type": "plot",
                        "title": "Vendas por categoria",
                        "library": "plotly",
                        "spec": {
                            "data": spec["data"],
                            "layout": spec["layout"]
                        }
                    }
                """
            },
            {
                "name": "Multiple subplots with graph_objects",
                "description": "For complex layouts (ACF/PACF, decomposition)",
                "code": """import plotly.graph_objects as go
                    from plotly.subplots import make_subplots
                    import json

                    fig = make_subplots(rows=2, cols=1, subplot_titles=("Série original", "ACF"))
                    fig.add_trace(go.Scatter(x=df["data"], y=df["vendas"], mode="lines"), row=1, col=1)
                    fig.add_trace(go.Bar(x=list(range(40)), y=acf_values), row=2, col=1)
                    fig.update_layout(title="Decomposição")

                    spec = json.loads(fig.to_json())

                    block = {
                        "type": "plot",
                        "title": "Decomposição",
                        "library": "plotly",
                        "spec": {
                            "data": spec["data"],
                            "layout": spec["layout"]
                        }
                    }
                """
            }
        ],
        "critical_rules": [
            "Always use plotly.express (px) first unless you need subplots or ACF/PACF",
            "Convert figure to JSON with json.loads(fig.to_json())",
            "Only include 'data' and 'layout' in spec, NOT config or frames",
            "For large series (>2000 points), downsample before plotting",
            "Handle datetime conversion with pd.to_datetime() before plotting",
            "Use default=str in json.dump() for numpy/datetime serialization"
        ]
    }


def build_context(
    task_id: str,
    output_name: str,
    step: dict,
    csv_paths: List[str],
    current_step: int,
    skill_context: Optional[str] = None
) -> ExecutionContextPackage:
    """
    Build complete execution context package.
    
    Args:
        task_id: Task ID
        output_name: Output name prefix (produces {output_name}_ui.json)
        step: Current step dict from plan (with description, reasoning, thinking_budget)
        csv_paths: List of CSV paths relative to workspace
        current_step: Current step number (1-indexed)
        skill_context: Optional skill context from helper_contet_agent
        
    Returns:
        ExecutionContextPackage ready for code generation
    """
    # 1. Step metadata
    step_meta = {
        "step_number": current_step,
        "description": step.get("description", ""),
        "reasoning": step.get("reasoning", ""),
        "thinking_budget": step.get("thinking_budget"),
        "output_type": step.get("output_type", "card")
    }
    
    # 2. Workspace paths
    output_dir = f"outputs/{task_id}/step_{current_step}"
    workspace_meta = {
        "cwd": ".",
        "path_note": (
            "Script runs with cwd=workspace. Use input_files, output_dir, "
            "and ui_json_path exactly as shown — do NOT prefix with 'workspace/'."
        ),
        "input_files": csv_paths,
        "output_dir": output_dir,
        "ui_json_path": f"{output_dir}/{output_name}_ui.json",
        "script_path": f"{output_dir}/script.py",
    }
    
    # 3. Data preview
    data_preview = _build_data_preview(csv_paths, max_rows=5)
    
    # 4. Previous steps summary
    previous_steps = _build_previous_steps_summary(task_id, current_step)
    
    # 5. Plotly contract
    plotly_contract = _build_plotly_contract()
    
    return ExecutionContextPackage(
        step=step_meta,
        workspace=workspace_meta,
        data_preview=data_preview,
        previous_steps=previous_steps,
        plotly_contract=plotly_contract,
        skill_context=skill_context
    )
