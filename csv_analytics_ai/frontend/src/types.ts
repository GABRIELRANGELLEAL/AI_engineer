export interface CreateTaskRequest {
  data_source_type: 'csv' | 'database';
  data_source_meta: {
    csv_path?: string;
    csv_paths?: string[];
    database_id?: string;
  };
  prompt: string;
}

export interface MessageRequest {
  prompt: string;
}

export interface PlannerTurnResponse {
  task_id: string;
  status: string;
  answer: string;
  plan: PlanItem[] | string[];
  discovery_log?: any[];
  interaction_id: string;
}

export interface PlanItem {
  step: number;
  description: string;
  reasoning?: string;
  thinking_budget?: number | null;
  output_type?: string;
  agent?: string;
}

export interface TaskResponse {
  task_id: string;
  status: string;
  data_source_type: string;
  data_source_meta: Record<string, string>;
  prompt: string;
  answer: string | null;
  plan: PlanItem[] | string[] | null;
  created_at: string;
  updated_at: string;
}

export interface InteractionResponse {
  id: string;
  agent: string;
  prompt: string;
  model_answer: string;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
}

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

export interface UploadedFile {
  name: string;
  path: string;
}

export interface UploadResponse {
  files: UploadedFile[];
}

export interface ExecutionState {
  output_name: string;
  steps: any[];
  current_step: number;
  completed_steps: number[];
  last_execution?: StepExecutionResult;
}

export interface StepExecutionResult {
  task_id: string;
  step_number: number;
  total_steps: number;
  step_description: string;
  status: 'completed' | 'error';
  summary: string;
  generated_files: string[];
  all_artifacts: Record<number, string[]>;
  next_step_ready: boolean;
  tool_uses_count: number;
  input_tokens: number;
  output_tokens: number;
}

export interface ExecutionStatusResponse {
  status: string;
  task_id: string;
  task_status: string;
  total_steps: number;
  current_step: number;
  completed_steps: number[];
  completed_count: number;
  execution_state: ExecutionState;
}
