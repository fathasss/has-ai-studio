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
}
