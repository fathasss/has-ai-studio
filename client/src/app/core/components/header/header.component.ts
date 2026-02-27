import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { NavigationEnd, Router } from '@angular/router';
import { OrchestratorService } from '../../../services/orchestrator.service';
import { SocketService } from '../../../services/socket.service';
import { filter } from 'rxjs/operators';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule],
  providers: [DatePipe],
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.scss']
})
export class HeaderComponent implements OnInit, OnDestroy {
  pageTitle: string = 'Dashboard';
  currentTime: string = '';
  uptime: string = '00:00:00';
  tokenRate: string = '0';
  
  private clockTimer: any;
  private uptimeTimer: any;
  private sub: Subscription | null = null;
  private lastUptimeSeconds: number = 0;

  constructor(
    private router: Router, 
    private orchestratorService: OrchestratorService,
    private socketService: SocketService,
    private datePipe: DatePipe
  ) {
    this.router.events.pipe(
      filter(event => event instanceof NavigationEnd)
    ).subscribe((event: any) => {
      this.updateTitle(event.urlAfterRedirects);
    });
  }

  ngOnInit() {
    this.updateClock();
    this.clockTimer = setInterval(() => this.updateClock(), 1000);

    // Initial fetch to avoid 00:00:00 on load
    this.orchestratorService.getMetrics().subscribe(res => {
      if (res && res.performance) {
        this.updateUptimeUI(res.performance.uptime_sec);
        this.tokenRate = Math.round(res.performance.token_rate_per_min || 0).toString();
      }
    });

    this.sub = this.socketService.systemUpdate$.subscribe({
      next: (res: any) => {
        if (res) {
          this.updateUptimeUI(res.uptime);
          this.tokenRate = Math.round(res.tokens_min || 0).toString();
        }
      },
      error: (err) => console.log('Metrics fetch error', err)
    });

    // Local tick fallback to keep UI alive even if socket is quiet
    this.uptimeTimer = setInterval(() => {
      this.lastUptimeSeconds++;
      this.updateUptimeUI(this.lastUptimeSeconds);
    }, 1000);
  }

  private updateUptimeUI(seconds: number) {
    this.lastUptimeSeconds = Math.floor(seconds || 0);
    const h = Math.floor(this.lastUptimeSeconds / 3600).toString().padStart(2, '0');
    const m = Math.floor((this.lastUptimeSeconds % 3600) / 60).toString().padStart(2, '0');
    const s = (this.lastUptimeSeconds % 60).toString().padStart(2, '0');
    this.uptime = `${h}:${m}:${s}`;
  }

  updateTitle(url: string) {
    if (url.includes('active-projects')) this.pageTitle = 'Active Projects';
    else if (url.includes('execution-traces')) this.pageTitle = 'Logs & Traces';
    else if (url.includes('settings')) this.pageTitle = 'Factory Configuration';
    else this.pageTitle = 'Dashboard';
  }

  updateClock() {
    this.currentTime = this.datePipe.transform(new Date(), 'MMM d, yyyy HH:mm:ss') || '';
  }

  ngOnDestroy() {
    if (this.clockTimer) clearInterval(this.clockTimer);
    if (this.uptimeTimer) clearInterval(this.uptimeTimer);
    if (this.sub) this.sub.unsubscribe();
  }
}
