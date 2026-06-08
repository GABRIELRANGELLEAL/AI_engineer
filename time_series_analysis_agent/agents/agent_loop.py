#!/usr/bin/env python3
"""
Generic Agentic Loop for LLM Interactions

A reusable, production-ready loop that handles all Claude API stop_reasons
and provides flexible tool execution for any agent implementation.

Usage:
    from agents.agent_loop import AgentLoop, AgentConfig
    
    config = AgentConfig(
        tools=my_tools_dict,
        model="claude-3-5-sonnet-20241022",
        max_tokens=4096,
        system_prompt="You are a helpful assistant.",
    )
    
    loop = AgentLoop(config=config, verbose=True)
    result = loop.run(user_message="Analyze this data...")
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union
from dotenv import load_dotenv
import anthropic

from .tools import execute_tool

load_dotenv()


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class AgentConfig:
    """Configuration for the agent loop."""
    
    # Tool configuration
    tools: List[Dict[str, Any]] = field(default_factory=list)
    """
    Tools configuration. Accepts two formats:
    
    1. List format (output from to_anthropic_tools() or to_openai_tools()):
       [
           {
               "name": "tool_name",
               "description": "Tool description",
               "input_schema": {...}
           }
       ]
    
    2. Dict format (legacy):
       {
           "tool_name": {
               "description": "Tool description",
               "input_schema": {...}
           }
       }
    
    Note: Tool handlers are resolved via execute_tool() which looks up tools
    from the global TOOLS dictionary. The tools here only need the schema
    information for the LLM API.
    """
    
    # LLM configuration
    model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 4096
    temperature: float = 1.0
    system_prompt: Optional[str] = None
    thinking_budget: Optional[int] = None
    """
    Tokens for extended thinking. None = disabled.
    Examples:
    - 2000 = brief thinking
    - 8000-10000 = deep thinking
    When enabled, temperature is automatically set to 1.0 (required by API)
    """
    
    # Loop configuration
    max_iterations: int = 10
    
    # Callback hooks: these are hooks that can be used to monitor and customize the agent loop
    on_tool_execute: Optional[Callable[[str, Dict, str], None]] = None
    """Called after tool execution: on_tool_execute(tool_name, tool_input, result)"""
    
    on_iteration_start: Optional[Callable[[int], None]] = None
    """Called at start of each iteration: on_iteration_start(iteration_number)"""
    
    on_iteration_end: Optional[Callable[[int, str], None]] = None
    """Called at end of each iteration: on_iteration_end(iteration_number, stop_reason)"""


@dataclass
class AgentResult:
    """Result from running the agent loop."""
    success: bool
    final_response: str
    stop_reason: str
    iterations: int
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    """Additional metadata (e.g., tool call history, timing info)"""


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def extract_text_response(response: anthropic.types.Message) -> str:
    """
    Extract text content from Claude's response.
    
    Automatically ignores:
    - thinking blocks (type == "thinking")
    - tool_use blocks
    - Any blocks without text content
    
    Args:
        response: Claude API response message
        
    Returns:
        Extracted text content, or empty string if no text found
    """
    try:
        text_parts = []
        if not response.content:
            return ""
        
        for block in response.content:
            # Skip thinking blocks explicitly (they don't have .text anyway)
            if hasattr(block, "type") and block.type == "thinking":
                continue
            
            # Extract text from text blocks only
            if hasattr(block, "text") and block.text:
                text_parts.append(block.text)
        
        return "\n".join(text_parts).strip()
    except Exception as e:
        # Log error but don't crash - return empty string as fallback
        print(f"Warning: Failed to extract text from response: {e}")
        return ""


# ============================================================================
# MAIN AGENT LOOP CLASS
# ============================================================================

class AgentLoop:
    """
    Generic agentic loop that handles all Claude API stop_reasons.
    
    Features:
    - Handles all stop_reasons: end_turn, tool_use, max_tokens, content_filter,
      pause_turn, stop_sequence
    - Flexible tool execution via handlers
    - Callback hooks for monitoring and customization
    - Comprehensive error handling
    - Detailed result metadata
    """
    
    def __init__(
        self,
        config: AgentConfig,
        verbose: bool = True,
        api_key: Optional[str] = None
    ):
        """
        Initialize the agent loop.
        
        Args:
            config: Agent configuration
            verbose: Whether to print detailed execution logs
            api_key: Optional Anthropic API key (uses env var if not provided)
        """
        self.config = config
        self.verbose = verbose
        
        # Initialize Anthropic client
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.client = anthropic.Anthropic(api_key=api_key)
        
        self.api_tools = self.config.tools
 
    def _log(self, message: str):
        """Print message if verbose mode is enabled."""
        if self.verbose:
            print(message)
    
    def run(
        self,
        user_message: str,
        initial_messages: Optional[List[Dict[str, Any]]] = None
    ) -> AgentResult:
        """
        Run the agentic loop with the given user message.
        
        Args:
            user_message: The user's input message
            initial_messages: Optional list of previous messages to continue from
        
        Returns:
            AgentResult with success status, response, and metadata
        """
        # Initialize message history
        if initial_messages:
            messages = initial_messages.copy()
            messages.append({"role": "user", "content": user_message})
        else:
            messages = [{"role": "user", "content": user_message}]
        
        self._log(f"\n👤 USER: {user_message}\n")
        self._log("=" * 80)
        
        iteration = 0
        final_response = ""
        last_stop_reason = None
        tool_call_history = []
        total_input_tokens = 0
        total_output_tokens = 0
        
        while iteration < self.config.max_iterations:
            iteration += 1
            
            # Call on_iteration_start hook
            if self.config.on_iteration_start:
                self.config.on_iteration_start(iteration)
            
            self._log(f"\n[Iteration {iteration}]")
            
            try:
                # ========== REQUEST TO CLAUDE ==========
                request_params = {
                    "model": self.config.model,
                    "max_tokens": self.config.max_tokens,
                    "messages": messages,
                }
                
                # this part is to Add optional parameters if them are provided
                if self.api_tools:
                    request_params["tools"] = self.api_tools
                
                if self.config.system_prompt:
                    request_params["system"] = self.config.system_prompt
                
                # Add thinking configuration if enabled
                if self.config.thinking_budget:
                    request_params["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": self.config.thinking_budget
                    }
                    # Temperature must be 1.0 when thinking is enabled (API requirement)
                    request_params["temperature"] = 1.0
                elif self.config.temperature != 1.0:
                    request_params["temperature"] = self.config.temperature
                
                response = self.client.messages.create(**request_params)
                
                # Track token usage
                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens
                
                last_stop_reason = response.stop_reason
                self._log(f"Stop reason: {response.stop_reason}")
                
                # Call on_iteration_end hook
                if self.config.on_iteration_end:
                    self.config.on_iteration_end(iteration, response.stop_reason)
                
                # ========== HANDLE STOP REASON ==========
                
                # 1️⃣ END_TURN - Normal completion
                if response.stop_reason == "end_turn":
                    self._log("\n✅ Claude finished normally (end_turn)")
                    self._log("-" * 80)
                    
                    final_response = extract_text_response(response)
                    self._log(final_response)
                    
                    return AgentResult(
                        success=True,
                        final_response=final_response,
                        stop_reason="end_turn",
                        iterations=iteration,
                        metadata={
                            "tool_call_history": tool_call_history,
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                        },
                    )
                
                # 2️⃣ TOOL_USE - Execute tools and continue
                elif response.stop_reason == "tool_use":
                    self._log("🔧 Claude requested tool use")
                    
                    # Add Claude's response to history
                    messages.append({"role": "assistant", "content": response.content})
                    
                    # Execute all requested tools
                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            tool_name = block.name
                            tool_input = block.input
                            tool_use_id = block.id
                            
                            self._log(f"   → Executing: {tool_name}")
                            self._log(f"     Input: {json.dumps(tool_input, indent=6)}")
                            
                            # Execute the tool using existing execute_tool function
                            result = execute_tool(tool_name, tool_input)
                            
                            # Log result preview
                            result_preview = result[:150] + "..." if len(result) > 150 else result
                            self._log(f"     Result: {result_preview}")
                            
                            # Call on_tool_execute hook
                            if self.config.on_tool_execute:
                                self.config.on_tool_execute(tool_name, tool_input, result)
                            
                            # Track tool call
                            tool_call_history.append({
                                "iteration": iteration,
                                "tool_name": tool_name,
                                "input": tool_input,
                                "result": result,
                            })
                            
                            # Add tool result
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": result,
                            })
                    
                    # Send results back to Claude
                    messages.append({
                        "role": "user",
                        "content": tool_results,
                    })
                    
                    # Continue loop
                    continue
                
                # 3️⃣ MAX_TOKENS - Response incomplete
                elif response.stop_reason == "max_tokens":
                    self._log("⚠️  MAX_TOKENS reached - response incomplete!")
                    self._log("   Claude hit token limit before finishing")
                    self._log("   → Continuing conversation to complete response...")
                    
                    # Add partial response and ask to continue
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({
                        "role": "user",
                        "content": "Please continue and complete your response."
                    })
                    
                    # Continue loop
                    continue
                
                # 4️⃣ CONTENT_FILTER - Policy violation
                elif response.stop_reason == "content_filter":
                    self._log("🚫 CONTENT_FILTER - Policy violation detected!")
                    
                    return AgentResult(
                        success=False,
                        final_response="",
                        stop_reason="content_filter",
                        iterations=iteration,
                        error="Claude's response triggered safety filters",
                        metadata={
                            "tool_call_history": tool_call_history,
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                        },
                    )
                
                # 5️⃣ PAUSE_TURN - Server tools still executing
                elif response.stop_reason == "pause_turn":
                    self._log("⏸️  PAUSE_TURN - Server tools still running...")
                    self._log("   → Continuing to wait for server tools to complete...")
                    
                    # Add response and continue
                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({
                        "role": "user",
                        "content": "Please continue."
                    })
                    
                    # Continue loop
                    continue
                
                # 6️⃣ STOP_SEQUENCE - Custom stop sequence triggered
                elif response.stop_reason == "stop_sequence":
                    self._log("🛑 STOP_SEQUENCE - Custom stop sequence triggered")
                    
                    final_response = extract_text_response(response)
                    
                    return AgentResult(
                        success=True,
                        final_response=final_response,
                        stop_reason="stop_sequence",
                        iterations=iteration,
                        metadata={
                            "tool_call_history": tool_call_history,
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                        },
                    )
                
                # 7️⃣ UNKNOWN - Unexpected stop reason
                else:
                    self._log(f"❓ Unknown stop_reason: {response.stop_reason}")
                    
                    return AgentResult(
                        success=False,
                        final_response=extract_text_response(response),
                        stop_reason=response.stop_reason,
                        iterations=iteration,
                        error=f"Unexpected stop_reason: {response.stop_reason}",
                        metadata={
                            "tool_call_history": tool_call_history,
                            "input_tokens": total_input_tokens,
                            "output_tokens": total_output_tokens,
                        },
                    )
                
            except anthropic.APIError as e:
                self._log(f"❌ API Error: {str(e)}")
                return AgentResult(
                    success=False,
                    final_response="",
                    stop_reason="api_error",
                    iterations=iteration,
                    error=str(e),
                    metadata={
                        "tool_call_history": tool_call_history,
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                    },
                )
            
            except anthropic.APIConnectionError as e:
                self._log(f"❌ Connection Error: {str(e)}")
                return AgentResult(
                    success=False,
                    final_response="",
                    stop_reason="connection_error",
                    iterations=iteration,
                    error=str(e),
                    metadata={
                        "tool_call_history": tool_call_history,
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                    },
                )
            
            except Exception as e:
                self._log(f"❌ Unexpected error: {str(e)}")
                return AgentResult(
                    success=False,
                    final_response="",
                    stop_reason="unexpected_error",
                    iterations=iteration,
                    error=str(e),
                    metadata={
                        "tool_call_history": tool_call_history,
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                    },
                )
        
        # ========== MAX ITERATIONS REACHED ==========
        self._log(f"\n❌ Max iterations ({self.config.max_iterations}) reached!")
        self._log(f"   Last stop_reason was: {last_stop_reason}")
        
        return AgentResult(
            success=False,
            final_response="",
            stop_reason="max_iterations_exceeded",
            iterations=iteration,
            error=f"Max iterations limit reached (last stop_reason: {last_stop_reason})",
            metadata={
                "tool_call_history": tool_call_history,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
            },
        )