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

  activeTab: string = 'TeamLead';
  agentTabs: string[] = ['TeamLead', 'DevOps', 'Frontend', 'Backend', 'Security', 'Tester'];
  expandedTraces: Set<string> = new Set();

  private sub: Subscription;

  constructor(
    private orchestratorService: OrchestratorService,
    private socketService: SocketService
  ) {
    this.sub = this.socketService.jobUpdate$.subscribe((data: any) => {
      // Refresh list if it's a new project or status is 'STARTED'
      if (!this.sprints.includes(data.sprint_id) || data.status === 'STARTED') {
        this.loadSprints();
      }

      // If update for current project, reload details
      if (this.activeSprint === data.sprint_id && this.activeSprint !== null) {
        this.loadSprintDetail(this.activeSprint);
        
        // Auto-switch tab if the agent is actively processing
        const agent = data.agent || data.agent_name;
        if (data.status === 'PROCESSING' || data.status === 'RUNNING') {
          if (this.agentTabs.includes(agent)) {
            this.activeTab = agent;
          }
        }
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
    this.activeTab = 'TeamLead'; // Reset tab when changing sprints
    this.loadSprintDetail(sprintId);
  }

  selectTab(tab: string) {
    this.activeTab = tab;
  }

  get filteredTraces() {
    let list = this.traces || [];
    if (this.activeTab !== 'Pipeline Detail') {
      list = list.filter(t => (t.agent === this.activeTab || t.agent_name === this.activeTab));
    }

    // Inject active jobs as "virtual traces" so user sees what agent is doing
    const activeJobs = this.jobs.filter(j => 
      j.status === 'PROCESSING' && 
      (this.activeTab === 'Pipeline Detail' || j.agent_name === this.activeTab)
    );

    const virtualTraces = activeJobs.map(j => ({
      agent: j.agent_name,
      timestamp: j.locked_at || new Date().toISOString(),
      response: `[IN PROGRESS] Working on task:\n${j.prompt}`,
      isVirtual: true
    }));

    // Merge and show newest first
    return [...virtualTraces, ...list].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }

  toggleTrace(timestamp: string) {
    if (this.expandedTraces.has(timestamp)) {
      this.expandedTraces.delete(timestamp);
    } else {
      this.expandedTraces.add(timestamp);
    }
  }

  isExpanded(timestamp: string): boolean {
    return this.expandedTraces.has(timestamp);
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
