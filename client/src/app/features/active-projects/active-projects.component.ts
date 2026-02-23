import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { OrchestratorService } from '../../services/orchestrator.service';
import { SocketService } from '../../services/socket.service';
import { Subscription, forkJoin } from 'rxjs';

@Component({
  selector: 'app-active-projects',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './active-projects.component.html',
  styleUrls: ['./active-projects.component.scss']
})
export class ActiveProjectsComponent implements OnInit, OnDestroy {
  sprints: string[] = [];
  activeSprint: string | null = null;
  
  jobs: any[] = [];
  traces: any[] = [];
  tlSummary: string = "";

  private sub: Subscription;

  constructor(
    private orchestratorService: OrchestratorService,
    private socketService: SocketService
  ) {
    this.sub = this.socketService.jobUpdate$.subscribe((data: any) => {
      // Eğer o an açık olan projeye ait bir güncelleme geldiyse detayları tekrar çek
      if (this.activeSprint === data.sprint_id && this.activeSprint !== null) {
        this.loadSprintDetail(this.activeSprint);
      }
    });
  }

  ngOnInit(): void {
    this.loadSprints();
  }

  loadSprints() {
    this.orchestratorService.getSprints().subscribe({
      next: (res) => {
        // Reverse array to show newest first
        this.sprints = (res.sprints || []).sort().reverse();
        
        // Eğer seçili bir şey yoksa ilkini otomatik seç (opsiyonel)
        if (!this.activeSprint && this.sprints.length > 0) {
           this.selectSprint(this.sprints[0]);
        }
      },
      error: (err) => console.error(err)
    });
  }

  selectSprint(sprintId: string) {
    this.activeSprint = sprintId;
    this.loadSprintDetail(sprintId);
  }

  loadSprintDetail(sid: string) {
    forkJoin({
      jobsRes: this.orchestratorService.getSprintJobs(sid),
      tracesRes: this.orchestratorService.getSprintTraces(sid)
    }).subscribe({
      next: ({ jobsRes, tracesRes }) => {
        this.jobs = jobsRes.jobs || [];
        this.traces = tracesRes.traces || [];
        
        // Find Summary from TeamLead JSON
        this.tlSummary = "";
        const tlTrace = this.traces.find(t => t.agent === 'TeamLead');
        if (tlTrace && tlTrace.response) {
          try {
            const match = tlTrace.response.match(/\{[\s\S]*\}/);
            if (match) {
              const plan = JSON.parse(match[0]);
              if (plan.summary_tr) {
                this.tlSummary = plan.summary_tr;
              }
            }
          } catch(e) {}
        }
      },
      error: (err) => console.error("Failed to load sprint detail", err)
    });
  }

  getJobStatus(role: string): string {
    const job = this.jobs.find(j => j.agent === role);
    if (job) return job.status;
    
    // Fallback uninitialized states
    if (['Security', 'Tester'].includes(role)) return 'STANDBY';
    if (['Frontend', 'Backend'].includes(role)) return 'AWAITING PLAN';
    return 'UNINITIALIZED';
  }

  ngOnDestroy(): void {
    if (this.sub) {
      this.sub.unsubscribe();
    }
  }
}
