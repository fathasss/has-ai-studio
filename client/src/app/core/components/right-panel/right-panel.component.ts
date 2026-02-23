import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { SocketService } from '../../../services/socket.service';
import { Subscription } from 'rxjs';

interface AgentStatus {
  name: string;
  status: 'IDLE' | 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';
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
    { name: 'TeamLead', status: 'IDLE' },
    { name: 'Frontend', status: 'IDLE' },
    { name: 'Backend', status: 'IDLE' },
    { name: 'Tester', status: 'IDLE' },
    { name: 'Security', status: 'IDLE' }
  ];

  private subJob: Subscription | undefined;
  private subSystem: Subscription | undefined;

  constructor(private socketService: SocketService) {}

  ngOnInit(): void {
    // Listen for real-time orchestrator updates
    this.subJob = this.socketService.jobUpdate$.subscribe((update: any) => {
      // update format from orchestrator expected: { job_id, agent: "Frontend", status: "PROCESSING" }
      const agentName = update.agent;
      const status = update.status;
      
      const idx = this.agents.findIndex(a => a.name === agentName);
      if (idx !== -1) {
        this.agents[idx].status = status;
        
        // Auto-reset COMPLETED/FAILED to IDLE after a delay
        if (status === 'COMPLETED' || status === 'FAILED') {
          setTimeout(() => {
            if (this.agents[idx].status === status) {
               this.agents[idx].status = 'IDLE';
            }
          }, 4000);
        }
      }
    });

    // Listen for metrics loop system updates
    this.subSystem = this.socketService.systemUpdate$.subscribe((update: any) => {
      if (update && update.agent_states) {
        Object.keys(update.agent_states).forEach(agentName => {
          const idx = this.agents.findIndex(a => a.name === agentName);
          if (idx !== -1) {
            // Sadece IDLE, PENDING, PROCESSING durumlarını metrics'ten alıyoruz
            // COMPLETED / FAILED gibi event tabanlı durumları jobUpdate$ üzerinden dinlemeye devam ediyoruz
            // Eğer agent şu anda COMPLETED/FAILED değilse güncelle
            if (this.agents[idx].status !== 'COMPLETED' && this.agents[idx].status !== 'FAILED') {
              this.agents[idx].status = update.agent_states[agentName];
            }
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
