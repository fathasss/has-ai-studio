import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { SocketService, SystemUpdate } from '../../../services/socket.service';
import { Subscription } from 'rxjs';

interface AgentStatus {
  name: string;
  role: string;
  status: 'WORKING' | 'AVAIL' | 'DOWN';
}

@Component({
  selector: 'app-right-panel',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './right-panel.component.html',
  styleUrls: ['./right-panel.component.scss']
})
export class RightPanelComponent implements OnInit, OnDestroy {
  agents: AgentStatus[] = [
    { name: 'TeamLead',   role: 'Solution Architect', status: 'AVAIL' },
    { name: 'DevOps',     role: 'Infrastructure Eng', status: 'AVAIL' },
    { name: 'Database',   role: 'Data Architect',     status: 'AVAIL' },
    { name: 'Backend',    role: 'API Engineer',       status: 'AVAIL' },
    { name: 'Frontend',   role: 'UI/UX Developer',    status: 'AVAIL' },
    { name: 'Security',   role: 'Security Auditor',   status: 'AVAIL' },
    { name: 'Tester',     role: 'Synthetic QA',       status: 'AVAIL' },
    { name: 'Documenter', role: 'Technical Writer',   status: 'AVAIL' }
  ];

  private subJob: Subscription | undefined;
  private subSystem: Subscription | undefined;

  constructor(private socketService: SocketService) {}

  ngOnInit(): void {
    // Listen for real-time job updates
    this.subJob = this.socketService.jobUpdate$.subscribe((update: any) => {
      const agentName = update.agent || update.agent_name;
      const rawStatus = update.status;
      
      const idx = this.agents.findIndex(a => a.name === agentName);
      if (idx !== -1) {
        if (rawStatus === 'WORKING' || rawStatus === 'PROCESSING' || rawStatus === 'RUNNING') {
          this.agents[idx].status = 'WORKING';
        } else if (rawStatus === 'COMPLETED' || rawStatus === 'SUCCESS' || rawStatus === 'FAILED' || rawStatus === 'IDLE' || rawStatus === 'PENDING') {
          this.agents[idx].status = 'AVAIL';
        }
      }
    });

    // Listen for system updates & agent states
    this.subSystem = this.socketService.systemUpdate$.subscribe((sys: SystemUpdate) => {
      if (sys && sys.agent_states) {
        this.agents.forEach(a => {
          const state = sys.agent_states[a.name];
          if (state === 'WORKING' || state === 'PROCESSING') {
            a.status = 'WORKING';
          } else if (state === 'AVAIL' || state === 'IDLE') {
            a.status = 'AVAIL';
          }
        });
      }
    });
  }

  ngOnDestroy(): void {
    if (this.subJob) {
      this.subJob.unsubscribe();
    }
    if (this.subSystem) {
      this.subSystem.unsubscribe();
    }
  }
}
