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
