import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { SocketService } from '../../../services/socket.service';
import { Subscription } from 'rxjs';

interface AgentStatus {
  name: string;
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
    { name: 'TeamLead', status: 'DOWN' },
    { name: 'DevOps', status: 'DOWN' },
    { name: 'Database', status: 'DOWN' },
    { name: 'Backend', status: 'DOWN' },
    { name: 'Frontend', status: 'DOWN' },
    { name: 'Security', status: 'DOWN' },
    { name: 'Tester', status: 'DOWN' },
    { name: 'Documenter', status: 'DOWN' }
  ];

  private subJob: Subscription | undefined;
  private subSystem: Subscription | undefined;

  constructor(private socketService: SocketService) {}

  ngOnInit(): void {
    // Listen for real-time orchestrator updates
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

    // Listen for metrics loop system updates
    this.subSystem = this.socketService.systemUpdate$.subscribe((update: any) => {
      if (update && update.agent_states) {
        this.agents.forEach(agent => {
          const backendState = update.agent_states[agent.name];
          if (backendState) {
            if (backendState === 'WORKING' || backendState === 'PROCESSING' || backendState === 'RUNNING') {
              agent.status = 'WORKING';
            } else {
              agent.status = 'AVAIL';
            }
          } else {
            // If agent not in states, it's likely DOWN/Disconnected
            agent.status = 'DOWN';
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
