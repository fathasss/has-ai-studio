import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { OrchestratorService } from '../../services/orchestrator.service';

@Component({
  selector: 'app-execution-traces',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './execution-traces.component.html',
  styleUrls: ['./execution-traces.component.scss']
})
export class ExecutionTracesComponent implements OnInit {
  traces: any[] = [];
  expandedLogs: Set<number> = new Set();
  activeTab: 'SYSTEM' | 'AGENT' = 'SYSTEM';

  constructor(private orchestratorService: OrchestratorService) {}

  ngOnInit(): void {
    this.loadTraces();
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
    return this.traces.filter(t => t.sprint_id !== 'idle');
  }

  get agentTraces() {
    return this.traces.filter(t => t.sprint_id === 'idle');
  }

  toggleLog(index: number) {
    if (this.expandedLogs.has(index)) {
      this.expandedLogs.delete(index);
    } else {
      this.expandedLogs.add(index);
    }
  }

  isExpanded(index: number): boolean {
    return this.expandedLogs.has(index);
  }
}
