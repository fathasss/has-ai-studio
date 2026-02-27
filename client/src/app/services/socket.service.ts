import { Injectable } from '@angular/core';
import { io, Socket } from 'socket.io-client';
import { Subject, Observable } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class SocketService {
  private socket: Socket;
  
  // Events
  public connected$ = new Subject<boolean>();
  public jobUpdate$ = new Subject<any>();
  public metricUpdate$ = new Subject<any>();
  public systemUpdate$ = new Subject<any>();
  public modelPullProgress$ = new Subject<any>();

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
      path: '/socket.io' // Proxy üzerinden gitmesi için ayarlanacak
    });

    this.socket.on('connect', () => {
      this.connected$.next(true);
    });

    this.socket.on('disconnect', () => {
      this.connected$.next(false);
    });

    this.socket.on('job_update', (data: any) => {
      this.jobUpdate$.next(data);
    });

    this.socket.on('metric_update', (data: any) => {
      this.metricUpdate$.next(data);
    });

    this.socket.on('system_update', (data: any) => {
      this.systemUpdate$.next(data);
    });

    this.socket.on('model_pull_progress', (data: any) => {
      this.updatePullState(data);
      this.modelPullProgress$.next(data);
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
    return new Observable<any>(observer => {
      this.socket.on(eventName, (data: any) => observer.next(data));
      return () => this.socket.off(eventName);
    });
  }

  disconnect() {
    if (this.socket) {
      this.socket.disconnect();
    }
  }
}
