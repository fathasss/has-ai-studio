import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { OrchestratorService } from '../../services/orchestrator.service';
import { SocketService } from '../../services/socket.service';
import { Subscription, forkJoin } from 'rxjs';

interface AgentConfig {
  id: string;
  name: string;
  avatar: string;
  color: string;
  glowColor: string;
  role: string;
  // Dynamic coordinates
  x: number;
  y: number;
  deskX: number;
  deskY: number;
  meetingX: number;
  meetingY: number;
  isFlipped: boolean; // to face left or right
  idleState?: 'WANDERING' | 'BREAK' | 'SERVER' | 'CHAT' | 'ARCADE' | 'WHITEBOARD' | 'LIBRARY';
}

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

  selectedAgent: string | null = null;
  expandedTraces: Set<string> = new Set();

  private sub: Subscription | null = null;
  private sysSub: Subscription | null = null;
  private movementTimer: any;

  // Floor layout configuration (pixels relative to .iso-office)
  // Desks aligned on the right side
  agents: AgentConfig[] = [
    { id: 'TeamLead',  name: 'Team Lead',  avatar: 'assets/avatars/teamlead.png',  color: '#facc15', glowColor: 'rgba(250,204,21,0.4)',  role: 'Planlama',  deskX: 750, deskY: 50,  meetingX: 350, meetingY: 250, x: 750, y: 50,  isFlipped: false },
    { id: 'DevOps',    name: 'DevOps',     avatar: 'assets/avatars/devops.png',    color: '#f97316', glowColor: 'rgba(249,115,22,0.4)',  role: 'Altyapı',   deskX: 750, deskY: 150, meetingX: 450, meetingY: 250, x: 750, y: 150, isFlipped: false },
    { id: 'Frontend',  name: 'Frontend',   avatar: 'assets/avatars/frontend.png',  color: '#06b6d4', glowColor: 'rgba(6,182,212,0.4)',   role: 'UI/UX',     deskX: 750, deskY: 250, meetingX: 520, meetingY: 330, x: 750, y: 250, isFlipped: false },
    { id: 'Backend',   name: 'Backend',    avatar: 'assets/avatars/backend.png',   color: '#10b981', glowColor: 'rgba(16,185,129,0.4)',  role: 'API',       deskX: 750, deskY: 350, meetingX: 450, meetingY: 400, x: 750, y: 350, isFlipped: false },
    { id: 'Security',  name: 'Security',   avatar: 'assets/avatars/security.png',  color: '#ef4444', glowColor: 'rgba(239,68,68,0.4)',   role: 'Güvenlik',  deskX: 750, deskY: 450, meetingX: 350, meetingY: 400, x: 750, y: 450, isFlipped: false },
    { id: 'Tester',    name: 'Tester',     avatar: 'assets/avatars/tester.png',    color: '#a855f7', glowColor: 'rgba(168,85,247,0.4)',  role: 'Test',      deskX: 750, deskY: 550, meetingX: 280, meetingY: 330, x: 750, y: 550, isFlipped: false },
  ];

  constructor(
    private orchestratorService: OrchestratorService,
    private socketService: SocketService
  ) {}

  ngOnInit(): void {
    this.loadSprints();

    this.sub = this.socketService.jobUpdate$.subscribe((data: any) => {
      if (!this.sprints.includes(data.sprint_id) || data.status === 'STARTED') {
        this.loadSprints();
      }

      if (this.activeSprint === data.sprint_id && this.activeSprint !== null) {
        const existingJob = this.jobs.find(j => j.id === data.job_id || (j.agent_name === (data.agent_name || data.agent) && j.status === 'PENDING'));

        if (existingJob) {
          existingJob.status = data.status === 'PROCESSING' ? 'WORKING' : data.status;
          if (data.status === 'COMPLETED') existingJob.status = 'COMPLETED';
        } else {
          this.jobs.push({
            id: data.job_id,
            agent_name: data.agent_name || data.agent,
            agent: data.agent_name || data.agent,
            status: data.status === 'PROCESSING' ? 'WORKING' : data.status,
            sprint_id: data.sprint_id
          });
        }

        this.loadSprintDetail(this.activeSprint);
      }
    });

    this.sysSub = this.socketService.systemUpdate$.subscribe((_data: any) => {});

    // Movement Loop for dynamic avatar positioning
    this.movementTimer = setInterval(() => this.updateAgentPositions(), 2000);
  }

  loadSprints() {
    this.orchestratorService.getSprints().subscribe({
      next: (res) => {
        this.sprints = (res.sprints || []).sort().reverse();
        if (!this.activeSprint && this.sprints.length > 0) {
          this.selectSprint(this.sprints[0]);
        }
      },
      error: (err) => console.error(err)
    });
  }

  selectSprint(sprintId: string) {
    this.activeSprint = sprintId;
    this.selectedAgent = null;
    this.loadSprintDetail(sprintId);
  }

  selectDesk(agentId: string) {
    this.selectedAgent = this.selectedAgent === agentId ? null : agentId;
  }

  closeDetail() {
    this.selectedAgent = null;
  }

  getJobStatus(role: string): string {
    const job = this.jobs.find(j => j.agent === role || j.agent_name === role);
    if (job) {
      if (job.status === 'PROCESSING') return 'WORKING';
      return job.status;
    }
    if (['Security', 'Tester'].includes(role)) return 'STANDBY';
    if (['Frontend', 'Backend'].includes(role)) return 'AWAITING';
    return 'IDLE';
  }

  getAgentStatusLabel(status: string): string {
    switch (status) {
      case 'WORKING': return '⚡ WORKING...';
      case 'COMPLETED': return '✅ COMPLETED';
      case 'PENDING': return '⏳ PENDING';
      case 'STANDBY': return '💤 STANDBY';
      case 'AWAITING': return '📋 AWAITING';
      default: return '○ IDLE';
    }
  }

  get selectedAgentTraces() {
    if (!this.selectedAgent) return [];
    let list = this.traces.filter(t => t.agent === this.selectedAgent || t.agent_name === this.selectedAgent);

    const activeJobs = this.jobs.filter(j =>
      j.status === 'PROCESSING' &&
      (j.agent_name === this.selectedAgent || j.agent === this.selectedAgent)
    );
    const virtualTraces = activeJobs.map(j => ({
      agent: j.agent_name,
      timestamp: j.locked_at || new Date().toISOString(),
      response: `[IN PROGRESS] Working on task:\n${j.prompt || 'Processing...'}`,
      prompt: j.prompt || '',
      isVirtual: true
    }));

    return [...virtualTraces, ...list].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }

  getAgentConfig(agentId: string): AgentConfig | undefined {
    return this.agents.find(a => a.id === agentId);
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
          } catch (e) { }
        }
      },
      error: (err) => console.error("Failed to load sprint detail", err)
    });
  }

  // Count completed agents for progress
  get completedCount(): number {
    return this.agents.filter(a => this.getJobStatus(a.id) === 'COMPLETED').length;
  }

  updateAgentPositions() {
    // Determine if TeamLead is working
    const isTeamLeadWorking = this.activeSprint ? this.getJobStatus('TeamLead') === 'WORKING' : false;

    this.agents.forEach(agent => {
      // If there is no active sprint, everyone is basically idle
      const status = this.activeSprint ? this.getJobStatus(agent.id) : 'IDLE';
      let prevX = agent.x;

      if (isTeamLeadWorking) {
        agent.x = agent.meetingX;
        agent.y = agent.meetingY;
      } else if (status === 'WORKING') {
        agent.x = agent.deskX;
        agent.y = agent.deskY;
      } else {
        if (Math.random() > 0.3) { // 70% chance to change state
          const rand = Math.random();
          
          if (rand < 0.3) {
            // Wander around empty space
            agent.idleState = 'WANDERING';
            agent.x = 200 + Math.random() * 200; 
            agent.y = 350 + Math.random() * 200;
          } else if (rand < 0.45) {
            // Coffee Break (Top Left)
            agent.idleState = 'BREAK';
            agent.x = 80 + Math.random() * 30; 
            agent.y = 80 + Math.random() * 30;
          } else if (rand < 0.60) {
            // Water Cooler (Top Center)
            agent.idleState = 'CHAT';
            agent.x = 420 + Math.random() * 40;
            agent.y = 80 + Math.random() * 30;
          } else {
            // Role specific
            if (agent.id === 'DevOps') {
               // Server Rack (Bottom Left)
               agent.idleState = 'SERVER';
               agent.x = 80 + Math.random() * 30;
               agent.y = 480 + Math.random() * 30;
            } else if (agent.id === 'Frontend' || agent.id === 'TeamLead') {
               // Whiteboard (Bottom Center)
               agent.idleState = 'WHITEBOARD';
               agent.x = 420 + Math.random() * 40;
               agent.y = 480 + Math.random() * 30;
            } else if (agent.id === 'Security' || agent.id === 'Backend') {
               // Library (Top Mid-Left)
               agent.idleState = 'LIBRARY';
               agent.x = 260 + Math.random() * 40;
               agent.y = 80 + Math.random() * 30;
            } else if (agent.id === 'Tester') {
               // Arcade (Mid Left)
               agent.idleState = 'ARCADE';
               agent.x = 80 + Math.random() * 30;
               agent.y = 280 + Math.random() * 30;
            }
          }
        }
      }

      agent.isFlipped = agent.x < prevX;
    });
  }

  ngOnDestroy(): void {
    if (this.sub) this.sub.unsubscribe();
    if (this.sysSub) this.sysSub.unsubscribe();
    if (this.movementTimer) clearInterval(this.movementTimer);
  }
}
