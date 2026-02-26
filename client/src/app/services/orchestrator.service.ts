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

  // State Persistence for Dashboard Chat
  public chatState: {
    currentSprintId: string,
    chatHistory: any[],
    rawAgentHistory: any[],
    selectedSession: string | null,
    isTyping: boolean,
    hasPendingPlan: boolean,
    draftPrompt: string
  } | null = null;

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

  migrateChatHistory(oldId: string, newId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/chat/history/migrate`, { old_id: oldId, new_id: newId });
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

  getChatSessions(): Observable<{sessions: {id: string, name: string}[]}> {
    return this.http.get<{sessions: {id: string, name: string}[]}>(`${this.apiUrl}/chat/sessions`);
  }

  getProjects(): Observable<{projects: string[]}> {
    return this.http.get<{projects: string[]}>(`${this.apiUrl}/projects`);
  }

  getProjectFiles(projectName: string): Observable<{files: string[]}> {
    return this.http.get<{files: string[]}>(`${this.apiUrl}/projects/${projectName}/files`);
  }

  getFileContent(projectName: string, filePath: string): Observable<{content: string, path: string}> {
    return this.http.get<{content: string, path: string}>(`${this.apiUrl}/projects/${projectName}/file`, {
      params: { path: filePath }
    });
  }

  getExceptions(): Observable<any> {
    return this.http.get(`${this.apiUrl}/exceptions`);
  }

  getReportSessions(): Observable<{sessions: string[]}> {
    return this.http.get<{sessions: string[]}>(`${this.apiUrl}/reports/sessions`);
  }

  getReportsForSession(sid: string): Observable<{files: string[]}> {
    return this.http.get<{files: string[]}>(`${this.apiUrl}/reports/${sid}/files`);
  }

  getReportContent(sid: string, filename: string): Observable<{content: string, filename: string}> {
    return this.http.get<{content: string, filename: string}>(`${this.apiUrl}/reports/${sid}/content`, {
      params: { filename }
    });
  }
}
