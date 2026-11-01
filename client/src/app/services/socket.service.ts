import { Injectable } from '@angular/core';
import { io, Socket } from 'socket.io-client';
import { BehaviorSubject, Subject, Observable } from 'rxjs';

export interface PullProgress {
  status: string;
  model: string;
  progress?: number;
  message?: string;
}

export interface JobUpdate {
  job_id: string;
  status: string;
  sprint_id: string;
  agent: string;
  agent_name: string;
}

export interface SystemUpdate {
  cpu: number;
  ram: number;
  gpu: number;
  disk: number;
  net_sent: number;
  net_recv: number;
  uptime: number;
  tokens_min: number;
  agent_states: Record<string, string>;
  timestamp: string;
}

export interface LiveTestStep {
  sprint_id: string;
  step: number;
  total: number;
  name: string;
  status: 'PASSED' | 'FAILED';
  duration_ms: number;
  details?: string;
  timestamp: string;
}

@Injectable({
  providedIn: 'root'
})
export class SocketService {
  private socket: Socket;
  
  // Events
  public connected$ = new BehaviorSubject<boolean>(false);
  public jobUpdate$ = new Subject<JobUpdate>();
  public metricUpdate$ = new Subject<any>();
  public systemUpdate$ = new Subject<SystemUpdate>();
  public modelPullProgress$ = new Subject<PullProgress>();
  public liveTestStep$ = new Subject<LiveTestStep>();
  public llmRoutingUpdate$ = new Subject<any>();
  public phaseUpdate$ = new Subject<any>();

  // Pull State Persistence
  public pullState = {
    isPulling: false,
    progress: 0,
    message: '',
    model: '',
    statusColor: 'text-gray-400'
  };

  constructor() {
    this.socket = io({
      path: '/socket.io',
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000
    });

    this.socket.on('connect', () => {
      this.connected$.next(true);
    });

    this.socket.on('disconnect', () => {
      this.connected$.next(false);
    });

    this.socket.on('job_update', (data: JobUpdate) => {
      this.jobUpdate$.next(data);
    });

    this.socket.on('metric_update', (data: any) => {
      this.metricUpdate$.next(data);
    });

    this.socket.on('system_update', (data: SystemUpdate) => {
      this.systemUpdate$.next(data);
    });

    this.socket.on('model_pull_progress', (data: PullProgress) => {
      this.updatePullState(data);
      this.modelPullProgress$.next(data);
    });

    this.socket.on('test_live_step', (data: LiveTestStep) => {
      this.liveTestStep$.next(data);
    });

    this.socket.on('llm_routing_updated', (data: any) => {
      this.llmRoutingUpdate$.next(data);
    });

    this.socket.on('phase_update', (data: any) => {
      this.phaseUpdate$.next(data);
    });
  }

  private updatePullState(data: any) {
    if (data.status === 'success') {
      this.pullState.progress = 100;
      this.pullState.statusColor = 'text-green-500';
      this.pullState.message = `Success: Model downloaded!`;
      
      // Auto-hide after 5 seconds
      setTimeout(() => {
        if (this.pullState.progress === 100) {
          this.pullState.isPulling = false;
        }
      }, 5000);
    } else if (data.status === 'error') {
      this.pullState.statusColor = 'text-red-500';
      this.pullState.message = `Error: ${data.message || 'Pull failed'}`;
      this.pullState.isPulling = false;
    } else {
      this.pullState.isPulling = true;
      this.pullState.model = data.model;
      this.pullState.progress = data.progress || 0;
      this.pullState.statusColor = 'text-blue-400';
      this.pullState.message = `Syncing: ${data.status} (${this.pullState.progress}%)`;
    }
  }

  public setPulling(model: string) {
    this.pullState.isPulling = true;
    this.pullState.model = model;
    this.pullState.progress = 0;
    this.pullState.statusColor = 'text-blue-400';
    this.pullState.message = `Initializing pull for ${model}...`;
  }

  onEvent(eventName: string): Observable<any> {
    return new Observable<any>((observer: any) => {
      const handler = (data: any) => observer.next(data);
      this.socket.on(eventName, handler);
      return () => this.socket.off(eventName, handler);
    });
  }

  disconnect() {
    if (this.socket) {
      this.socket.disconnect();
    }
  }
}
