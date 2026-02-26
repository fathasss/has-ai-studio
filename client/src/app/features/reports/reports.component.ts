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
  reportsBySession: { [key: string]: string[] } = {};
  expandedSessions: Set<string> = new Set();
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

  isExpanded(sid: string): boolean {
    return this.expandedSessions.has(sid);
  }

  loadReportsForSession(sid: string) {
    this.orchestratorService.getReportsForSession(sid).subscribe({
      next: (res: { files: string[] }) => {
        this.reportsBySession[sid] = res.files || [];
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

  formatAgentName(filename: string): string {
    return filename.split('-report_')[0];
  }

  formatDate(filename: string): string {
    const parts = filename.split('_');
    if (parts.length < 2) return '';
    const dateStr = parts[parts.length - 2];
    const timeStr = parts[parts.length - 1].split('.')[0];
    
    // YYYYMMDD -> DD/MM/YYYY
    const y = dateStr.substring(0, 4);
    const m = dateStr.substring(4, 6);
    const d = dateStr.substring(6, 8);
    
    // HHMMSS -> HH:MM
    const hh = timeStr.substring(0, 2);
    const mm = timeStr.substring(2, 4);
    
    return `${d}/${m}/${y} ${hh}:${mm}`;
  }
}
