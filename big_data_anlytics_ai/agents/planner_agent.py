#!/usr/bin/env python3
"""
Planning agents for the multi-agent workflow.

- questioner_agent: Refines a raw user prompt into a structured brief with questions
- planner_agent: Creates human-readable step-by-step plans for user validation
"""

import json
import os
import re
from dotenv import load_dotenv
import ast
from typing import Any, List, Optional

from .tools import to_anthropic_tools
from .agent_loop import AgentLoop, AgentConfig

load_dotenv()


def _parse_planner_response_fixed(text: str) -> dict:
    """Parse planner response and extract answer and plan."""
    text = text.strip()
    
    # Try to extract JSON/dict from code blocks first
    # Pattern: ```json ... ``` or ```python ... ``` or ``` ... ```
    code_block_pattern = r"```(?:json|python)?\s*(\{[\s\S]*?\})\s*```"
    code_match = re.search(code_block_pattern, text)
    
    if code_match:
        # Extract the dict/JSON from within code block
        text = code_match.group(1).strip()
    else:
        # Try stripping outer code fences if present
        if "```" in text:
            text = re.sub(r"^```(?:python|json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            text = text.strip()
    
    # Try parsing as JSON
    try:
        parsed = json.loads(text)
        return {
            "answer": parsed.get("answer", ""),
            "plan": parsed.get("plan", []),
        }
    except json.JSONDecodeError:
        pass
    
    # Try parsing as Python literal
    try:
        parsed = ast.literal_eval(text)
        return {
            "answer": parsed.get("answer", ""),
            "plan": parsed.get("plan", []),
        }
    except (ValueError, SyntaxError):
        pass
    
    # If all parsing fails, treat as plain text answer with no plan
    # This happens when agent is still exploring or asking questions
    return {
        "answer": text,
        "plan": []
    }


def format_plan_as_text(result: dict[str, Any]) -> str:
    """
    Format planner output for downstream agents that expect a single text plan.
    Handles both old format (steps as strings) and new format (steps as dicts).
    """
    parts = [result.get("answer", "")]
    
    for i, step in enumerate(result.get("plan", []), start=1):
        # Handle new format (dict with description, reasoning, thinking_budget)
        if isinstance(step, dict):
            description = step.get("description", "")
            reasoning = step.get("reasoning", "")
            thinking = step.get("thinking_budget")
            
            step_text = f"\nStep {i}: {description}"
            if reasoning:
                step_text += f"\n  Reasoning: {reasoning}"
            if thinking:
                step_text += f"\n  Thinking Budget: {thinking} tokens"
            
            parts.append(step_text)
        # Handle old format (steps as strings) - backward compatibility
        else:
            parts.append(f"\nStep {i}: {step}")
    
    return "\n".join(parts).strip()


def get_step_thinking_budget(step: Any) -> Optional[int]:
    """
    Extract thinking_budget from a plan step.
    
    Args:
        step: Plan step (can be dict with thinking_budget or string)
        
    Returns:
        thinking_budget value (int or None)
    """
    if isinstance(step, dict):
        thinking = step.get("thinking_budget")
        # Handle both None and null values
        return thinking if thinking is not None else None
    return None


def planner_agent_file(
    prompt: str,
    conversation_history: Optional[List[dict[str, str]]] = None,
    input_files: str = "",
    model_name: str = "claude-haiku-4-5-20251001",
) -> tuple[Any, dict[str, Any]]:
    """
    Generate plan with optional discovery phase.
    
    The agent can use tools to explore workspace files before creating the plan.
    Discovery loop continues until agent returns a plan (no more tool uses).
    
    NEW: Each plan step now includes thinking_budget to optimize LLM usage:
    - None: Simple tasks (data loading, basic operations)
    - 2000: Brief thinking (moderate analysis)
    - 5000-8000: Medium thinking (pattern detection, complex analysis)
    - 8000-10000: Deep thinking (critical reasoning, model selection)
    
    Args:
        prompt: Current user message (initial prompt or follow-up reply)
        conversation_history: Optional prior messages (Anthropic format)
        input_files: String describing available input files
        model_name: Claude model to use for planning
    
    Returns:
        (raw_response, output_dict)
        
    Example output:
        {
            "answer": "Here's your analysis plan...",
            "plan": [
                {
                    "description": "Load CSV data",
                    "reasoning": "Simple I/O operation",
                    "thinking_budget": None
                },
                {
                    "description": "Detect anomalies in time series",
                    "reasoning": "Complex pattern recognition required",
                    "thinking_budget": 8000
                }
            ]
        }
    """
    
    example_json = {
        "answer": "I've analyzed your data and created this plan. Does this approach work for you?",
        "plan": [
            {
                "description": "Load and validate the CSV file: check for missing values and data types",
                "reasoning": "Simple data loading task - no complex thinking needed",
                "thinking_budget": None
            },
            {
                "description": "Perform exploratory data analysis: generate summary statistics and visualizations",
                "reasoning": "Requires analysis of patterns and relationships in data",
                "thinking_budget": 5000
            }
        ]
    }
    
    system_prompt = f"""
        You are a planning agent for analytical and data processing tasks.

        DISCOVERY PHASE:
        You have tools to explore the workspace before creating a plan:
        - view_file: Read file contents (shows first 10 lines for CSV)
        - search_files: Find files matching patterns (e.g., "*.csv")
        - get_file_stats: Get file metadata (size, line count, modified date)

        Use these tools to understand:
        - What data files are available
        - Data structure (columns, data types, formats)
        - Data quality issues (missing values, date ranges)
        - File sizes and complexity

        PLANNING PHASE:
        After exploring (or if you already have enough context), create a step-by-step plan.

        When request is vague or missing details:
        - Ask clarifying questions in "answer"
        - Return empty "plan" list
        - User will reply with more context

        When you have enough context:
        - Return a detailed step-by-step plan (max 7 steps)
        - Each step MUST be a dictionary with:
          * "description": What to do (clear, actionable)
          * "reasoning": Why this step needs thinking (or doesn't)
          * "thinking_budget": Token budget for extended thinking
            - None or null = No thinking needed (simple tasks like data loading, basic operations)
            - 2000 = Brief thinking (moderate complexity, quick analysis)
            - 5000-8000 = Medium thinking (complex analysis, pattern recognition)
            - 8000-10000 = Deep thinking (critical reasoning, complex decision-making)
        
        THINKING BUDGET GUIDELINES:
        - Simple data operations (load, save, filter): None
        - Basic calculations and transformations: None or 2000
        - Pattern analysis, anomaly detection: 5000-8000
        - Complex statistical analysis: 8000-10000
        - Model selection and evaluation: 8000-10000
        - Report generation: 2000

        - Format as valid Python dict (no markdown, no code fences)

        INPUT FILES CONTEXT:
        {input_files}

        OUTPUT FORMAT:
        {json.dumps(example_json, indent=2)}
    """
    
    # Configure the agent loop for planning
    # Use to_anthropic_tools to get tools in the correct format
    config = AgentConfig(
        tools=to_anthropic_tools(["view_file", "search_files", "get_file_stats"]),
        model=model_name,
        max_tokens=2048,
        temperature=0.3,
        system_prompt=system_prompt,
        max_iterations=8,
    )
    
    # Run the agent loop
    loop = AgentLoop(config=config, verbose=False)
    result = loop.run(
        user_message=prompt,
        initial_messages=conversation_history
    )
    
    # Parse the response
    if result.success:
        model_answer = _parse_planner_response_fixed(result.final_response)
    else:
        # Fallback on error
        model_answer = {
            "answer": f"Planning failed: {result.error or 'Unknown error'}",
            "plan": []
        }
    
    # Build output dict
    output = {
        "prompt": prompt,
        "model_answer": model_answer,
        "input_tokens": result.metadata.get("input_tokens", 0),
        "output_tokens": result.metadata.get("output_tokens", 0),
        "tool_uses": result.metadata.get("tool_call_history", []),
        "iterations": result.iterations,
        "stop_reason": result.stop_reason,
    }
    
    # Note: We don't have access to raw_response anymore with AgentLoop
    # Return None as first element (can be changed if raw response is needed)
    return None, output


def build_conversation_history(interactions: list) -> list[dict]:
    """
    Build Anthropic conversation history from stored planner interactions.
    
    Args:
        interactions: List of LlmInteraction rows (agent="planner") ordered by created_at
        
    Returns:
        List of message dicts in Anthropic format
    """
    messages = []
    for interaction in interactions:
        if getattr(interaction, "agent", "planner") != "planner":
            continue
        messages.append({"role": "user", "content": interaction.prompt})
        # model_answer is stored as JSON text in the database
        assistant_content = interaction.model_answer
        if isinstance(assistant_content, str):
            try:
                parsed = json.loads(assistant_content)
                if isinstance(parsed, dict) and "answer" in parsed:
                    assistant_content = json.dumps(parsed)
            except json.JSONDecodeError:
                pass
        elif isinstance(assistant_content, dict):
            assistant_content = json.dumps(assistant_content)
        messages.append({"role": "assistant", "content": assistant_content})
    return messages
