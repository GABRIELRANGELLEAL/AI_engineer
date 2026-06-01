import axios from 'axios';
import type {
  CreateTaskRequest,
  MessageRequest,
  PlannerTurnResponse,
  TaskResponse,
  InteractionResponse,
  UploadResponse,
  UploadedFile,
} from './types';

const API_BASE_URL = '/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

export const uploadCsvFiles = async (files: File[]): Promise<UploadedFile[]> => {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append('files', file);
  });

  const response = await axios.post<UploadResponse>(
    `${API_BASE_URL}/uploads/csv`,
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  );

  return response.data.files;
};

export const createTask = async (request: CreateTaskRequest): Promise<PlannerTurnResponse> => {
  const response = await api.post<PlannerTurnResponse>('/tasks', request);
  return response.data;
};

export const sendMessage = async (
  taskId: string,
  request: MessageRequest
): Promise<PlannerTurnResponse> => {
  const response = await api.post<PlannerTurnResponse>(
    `/tasks/${taskId}/messages`,
    request
  );
  return response.data;
};

export const getTask = async (taskId: string): Promise<TaskResponse> => {
  const response = await api.get<TaskResponse>(`/tasks/${taskId}`);
  return response.data;
};

export const getInteractions = async (taskId: string): Promise<InteractionResponse[]> => {
  const response = await api.get<InteractionResponse[]>(`/tasks/${taskId}/interactions`);
  return response.data;
};

export const proceedTask = async (taskId: string): Promise<{ status: string; task_id: string; message: string }> => {
  const response = await api.post(`/tasks/${taskId}/proceed`);
  return response.data;
};

export const executeTask = async (taskId: string, selectedSteps?: number[]): Promise<any> => {
  const response = await api.post(`/tasks/${taskId}/execute`, {
    selected_steps: selectedSteps && selectedSteps.length > 0 ? selectedSteps : null
  });
  return response.data;
};
