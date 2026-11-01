import { Component, OnInit, OnDestroy, Input, Output, EventEmitter } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { NavigationEnd, Router } from '@angular/router';
import { OrchestratorService } from '../../../services/orchestrator.service';
import { SocketService } from '../../../services/socket.service';
import { I18nService, AppLang } from '../../services/i18n.service';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { filter } from 'rxjs/operators';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule, TranslatePipe],
  providers: [DatePipe],
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.scss']
})
export class HeaderComponent implements OnInit, OnDestroy {
  @Input() rightPanelOpen: boolean = true;
  @Output() toggleRightPanel = new EventEmitter<void>();

  pageTitle: string = 'AI Development Office';
  currentTime: string = '';
  uptime: string = '00:00:00';
  tokenRate: string = '0';
  currentLang: AppLang = 'tr';
  
  private clockTimer: any;
  private uptimeTimer: any;
  private sub: Subscription | null = null;
  private routerSub: Subscription | null = null;
  private langSub: Subscription | null = null;
  private lastUptimeSeconds: number = 0;

  constructor(
    private router: Router, 
    private orchestratorService: OrchestratorService,
    private socketService: SocketService,
    private datePipe: DatePipe,
    public i18n: I18nService
  ) {
    this.currentLang = this.i18n.currentLang;
    this.routerSub = this.router.events.pipe(
      filter(event => event instanceof NavigationEnd)
    ).subscribe((event: any) => {
      this.updateTitle(event.urlAfterRedirects);
    });

    this.langSub = this.i18n.lang$.subscribe((lang) => {
      this.currentLang = lang;
      this.updateTitle(this.router.url);
    });
  }

  public switchLanguage(lang: AppLang): void {
    this.i18n.setLanguage(lang);
  }

  ngOnInit() {
    this.updateTitle(this.router.url);
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
    if (url.includes('active-projects')) this.pageTitle = this.i18n.t('header.officeTitle');
    else if (url.includes('dashboard')) this.pageTitle = this.i18n.t('header.missionHubTitle');
    else if (url.includes('projects')) this.pageTitle = this.i18n.t('header.projectsTitle');
    else if (url.includes('reports')) this.pageTitle = this.i18n.t('header.reportsTitle');
    else if (url.includes('execution-traces')) this.pageTitle = this.i18n.t('header.tracesTitle');
    else if (url.includes('exceptions')) this.pageTitle = this.i18n.t('header.exceptionsTitle');
    else if (url.includes('settings')) this.pageTitle = this.i18n.t('header.settingsTitle');
    else this.pageTitle = this.i18n.t('header.officeTitle');
  }

  updateClock() {
    this.currentTime = this.datePipe.transform(new Date(), 'MMM d, yyyy HH:mm:ss') || '';
  }

  ngOnDestroy() {
    if (this.clockTimer) clearInterval(this.clockTimer);
    if (this.uptimeTimer) clearInterval(this.uptimeTimer);
    if (this.sub) this.sub.unsubscribe();
    if (this.routerSub) this.routerSub.unsubscribe();
    if (this.langSub) this.langSub.unsubscribe();
  }
}
