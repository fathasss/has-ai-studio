import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface DefaultConfig {
  AGENT_MODEL: string;
  OLLAMA_URL: string;
  LLM_PROVIDER: string;
}

export interface MetricData {
  performance: {
    total_tokens: number;
    token_rate_per_min: number;
    uptime_sec: number;
  }
}

@Injectable({
  providedIn: 'root'
})
export class OrchestratorService {
  private apiUrl = '/api';

  constructor(private http: HttpClient) { }

  getConfig(): Observable<DefaultConfig> {
    return this.http.get<DefaultConfig>(`${this.apiUrl}/config`);
  }

  saveConfig(config: DefaultConfig): Observable<any> {
    return this.http.post(`${this.apiUrl}/config`, config);
  }

  getSystemStatus(): Observable<any> {
    return this.http.get(`${this.apiUrl}/system/status`);
  }

  getMetrics(): Observable<MetricData> {
    return this.http.get<MetricData>(`${this.apiUrl}/metrics`);
  }

  getSprints(): Observable<{sprints: string[]}> {
    return this.http.get<{sprints: string[]}>(`${this.apiUrl}/sprints`);
  }

  getSprintJobs(sprintId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/jobs/${sprintId}`);
  }

  getSprintTraces(sprintId: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/traces/${sprintId}`);
  }

  getGlobalTraces(): Observable<any> {
    return this.http.get(`${this.apiUrl}/traces`);
  }

  getOllamaModels(): Observable<{models: string[]}> {
    return this.http.get<{models: string[]}>(`${this.apiUrl}/ollama/models`);
  }

  pullOllamaModel(modelName: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/ollama/pull`, { model: modelName });
  }

  chatTeamLead(history: any[]): Observable<any> {
    return this.http.post(`${this.apiUrl}/chat/teamlead`, { history });
  }

  previewSprint(history: any[]): Observable<any> {
    return this.http.post(`${this.apiUrl}/chat/preview`, { history });
  }

  executeSprint(sprintId: string, plan: any, history: any[]): Observable<any> {
    return this.http.post(`${this.apiUrl}/sprint/execute`, { sprint_id: sprintId, plan, history });
  }

  submitLlmJob(jobRequest: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/llm/submit`, jobRequest);
  }

  getChatHistory(sprintId: string): Observable<any[]> {
    return this.http.get<any[]>(`${this.apiUrl}/chat/history/${sprintId}`);
  }

  saveChatMessage(sprintId: string, role: string, content: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/chat/history`, { sprint_id: sprintId, role, content });
  }

  getChatSessions(): Observable<{sessions: string[]}> {
    return this.http.get<{sessions: string[]}>(`${this.apiUrl}/chat/sessions`);
  }
}
