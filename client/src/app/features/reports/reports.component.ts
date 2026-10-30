import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { OrchestratorService } from '../../services/orchestrator.service';
import { marked } from 'marked';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

@Component({
  selector: 'app-reports',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './reports.component.html',
  styleUrls: ['./reports.component.scss']
})
export class ReportsComponent implements OnInit {
  sessions: string[] = [];
  activeSession: string | null = null;
  reportsBySession: { [sid: string]: { [agent: string]: string[] } } = {};
  expandedSessions: Set<string> = new Set();
  expandedAgents: Set<string> = new Set(); // Stores "sid/agent"
  activeReport: string | null = null;
  reportId: string | null = null; // Full path for report
  reportContent: SafeHtml | null = null;
  isLoading: boolean = false;

  constructor(
    private orchestratorService: OrchestratorService,
    private sanitizer: DomSanitizer
  ) {}

  ngOnInit(): void {
    this.loadSessions();
  }

  loadSessions() {
    this.orchestratorService.getReportSessions().subscribe({
      next: (res: { sessions: string[] }) => {
        this.sessions = res.sessions || [];
        if (this.sessions.length > 0 && this.expandedSessions.size === 0) {
          this.toggleSession(this.sessions[0]);
        }
      },
      error: (err: any) => console.error('Failed to load sessions', err)
    });
  }

  toggleSession(sid: string) {
    if (this.expandedSessions.has(sid)) {
      this.expandedSessions.delete(sid);
    } else {
      this.expandedSessions.add(sid);
      if (!this.reportsBySession[sid]) {
        this.loadReportsForSession(sid);
      }
    }
  }

  toggleAgentFolder(sid: string, agent: string) {
    const key = `${sid}/${agent}`;
    if (this.expandedAgents.has(key)) {
      this.expandedAgents.delete(key);
    } else {
      this.expandedAgents.add(key);
    }
  }

  isExpanded(sid: string): boolean {
    return this.expandedSessions.has(sid);
  }

  isAgentExpanded(sid: string, agent: string): boolean {
    return this.expandedAgents.has(`${sid}/${agent}`);
  }

  getAgentsInSession(sid: string): string[] {
    return this.reportsBySession[sid] ? Object.keys(this.reportsBySession[sid]) : [];
  }

  loadReportsForSession(sid: string) {
    this.orchestratorService.getReportsForSession(sid).subscribe({
      next: (res: { files: string[] }) => {
        const grouped: { [agent: string]: string[] } = {};
        (res.files || []).forEach(file => {
          const agent = file.includes('/') ? file.split('/')[0] : 'General';
          if (!grouped[agent]) grouped[agent] = [];
          grouped[agent].push(file);
        });
        this.reportsBySession[sid] = grouped;
      },
      error: (err: any) => console.error('Failed to load reports', err)
    });
  }

  selectReport(sid: string, filename: string) {
    this.activeSession = sid;
    this.activeReport = filename;
    this.reportId = `${sid}/${filename}`;
    this.isLoading = true;
    this.orchestratorService.getReportContent(sid, filename).subscribe({
      next: (res: { content: string }) => {
        this.reportContent = this.renderMarkdown(res.content);
        this.isLoading = false;
      },
      error: (err: any) => {
        console.error('Failed to load report content', err);
        this.isLoading = false;
      }
    });
  }

  renderMarkdown(content: string): SafeHtml {
    const rawHtml = marked(content);
    return this.sanitizer.bypassSecurityTrustHtml(rawHtml as string);
  }

  formatAgentName(path: string): string {
    if (path.includes('/')) {
      return path.split('/')[0];
    }
    return path.replace('report_', '').replace('.md', '').split('_')[0];
  }

  formatDate(path: string): string {
    const filename = path.includes('/') ? path.split('/').pop() || '' : path;
    const parts = filename.split('_');
    if (parts.length >= 3 && parts[1].length === 8) {
      const datePart = parts[1]; // 20260303
      const timePart = parts[2].split('.')[0]; // 112203
      
      const y = datePart.substring(0, 4);
      const m = datePart.substring(4, 6);
      const d = datePart.substring(6, 8);
      
      const hh = timePart.substring(0, 2);
      const mm = timePart.substring(2, 4);
      const ss = timePart.length >= 6 ? ':' + timePart.substring(4, 6) : '';
      
      return `${d}/${m}/${y} ${hh}:${mm}${ss}`;
    }
    return filename;
  }
}
