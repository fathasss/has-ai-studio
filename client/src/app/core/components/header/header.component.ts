import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { NavigationEnd, Router } from '@angular/router';
import { OrchestratorService, MetricData } from '../../../services/orchestrator.service';
import { filter } from 'rxjs/operators';

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
  private metricsTimer: any;

  constructor(
    private router: Router, 
    private orchestratorService: OrchestratorService,
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

    this.fetchMetrics();
    this.metricsTimer = setInterval(() => this.fetchMetrics(), 5000);
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

  fetchMetrics() {
    this.orchestratorService.getMetrics().subscribe({
      next: (res: MetricData) => {
        const seconds = Math.floor(res.performance.uptime_sec);
        const h = Math.floor(seconds / 3600).toString().padStart(2, '0');
        const m = Math.floor((seconds % 3600) / 60).toString().padStart(2, '0');
        const s = (seconds % 60).toString().padStart(2, '0');
        this.uptime = `${h}:${m}:${s}`;
        this.tokenRate = Math.round(res.performance.token_rate_per_min).toString();
      },
      error: (err) => console.log('Metrics fetch error', err)
    });
  }

  ngOnDestroy() {
    if (this.clockTimer) clearInterval(this.clockTimer);
    if (this.metricsTimer) clearInterval(this.metricsTimer);
  }
}
