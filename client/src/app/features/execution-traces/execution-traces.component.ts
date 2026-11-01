import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { OrchestratorService } from '../../services/orchestrator.service';
import { TranslatePipe } from '../../core/pipes/translate.pipe';

@Component({
  selector: 'app-execution-traces',
  standalone: true,
  imports: [CommonModule, TranslatePipe],
  templateUrl: './execution-traces.component.html',
  styleUrls: ['./execution-traces.component.scss']
})
export class ExecutionTracesComponent implements OnInit {
  traces: any[] = [];
  expandedLogs: Set<number> = new Set();
  collapsedGroups: Set<string> = new Set();
  activeTab: 'SYSTEM' | 'AGENT' = 'SYSTEM';

  // Agent Metadata for richer UI
  AGENT_METADATA: { [key: string]: any } = {
    'TeamLead':   { color: '#facc15', avatar: 'assets/avatars/teamlead.png', role: 'Senior Tech Lead' },
    'DevOps':     { color: '#06b6d4', avatar: 'assets/avatars/devops.png', role: 'SRE & DevOps Architect' },
    'Database':   { color: '#14b8a6', avatar: 'assets/avatars/backend.png', role: 'Data Architect & DBA' },
    'Backend':    { color: '#10b981', avatar: 'assets/avatars/backend.png', role: 'Senior Systems Architect' },
    'Frontend':   { color: '#3b82f6', avatar: 'assets/avatars/frontend.png', role: 'Senior UI/UX Architect' },
    'Security':   { color: '#a855f7', avatar: 'assets/avatars/security.png', role: 'CISO / Security Guru' },
    'Tester':     { color: '#f43f5e', avatar: 'assets/avatars/tester.png', role: 'QA Lead Architect' },
    'Documenter': { color: '#38bdf8', avatar: 'assets/avatars/teamlead.png', role: 'Lead Technical Writer' },
    '_default':   { color: '#71717a', avatar: 'assets/logo.png', role: 'Senior Engineer' }
  };

  constructor(private orchestratorService: OrchestratorService) {}

  ngOnInit(): void {
    this.loadTraces();
  }

  getAgentMeta(name: string) {
    return this.AGENT_METADATA[name] || this.AGENT_METADATA['_default'];
  }

  toggleGroup(name: string) {
    if (this.collapsedGroups.has(name)) {
      this.collapsedGroups.delete(name);
    } else {
      this.collapsedGroups.add(name);
    }
  }

  isGroupCollapsed(name: string): boolean {
    return this.collapsedGroups.has(name);
  }

  loadTraces() {
    this.orchestratorService.getGlobalTraces().subscribe({
      next: (res) => {
        this.traces = res.traces || [];
      },
      error: (err) => console.error("Failed to load global traces", err)
    });
  }

  get systemTraces() {
    return this.traces.filter(t => t.sprint_id && t.sprint_id !== 'idle');
  }

  get agentTraces() {
    return this.traces.filter(t => !t.sprint_id || t.sprint_id === 'idle' || t.job_id === 'idle');
  }

  get groupedAgentTraces() {
    const groups: { [key: string]: any[] } = {};
    this.agentTraces.forEach(t => {
      const name = t.agent_name || t.agent || 'Unknown';
      if (!groups[name]) groups[name] = [];
      groups[name].push(t);
    });
    return groups;
  }

  toggleLog(id: string) {
    if (this.expandedLogs.has(id as any)) {
      this.expandedLogs.delete(id as any);
    } else {
      this.expandedLogs.add(id as any);
    }
  }

  isExpanded(id: string): boolean {
    return this.expandedLogs.has(id as any);
  }
}
