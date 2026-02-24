import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { OrchestratorService } from '../../services/orchestrator.service';
import { SocketService } from '../../services/socket.service';
import { Subscription } from 'rxjs';

interface ProjectException {
  id: number;
  sprint_id: string;
  source: string;
  command: string;
  error_message: string;
  timestamp: string;
}

@Component({
  selector: 'app-exceptions',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './exceptions.component.html',
  styleUrl: './exceptions.component.scss'
})
export class ExceptionsComponent implements OnInit, OnDestroy {
  exceptions: ProjectException[] = [];
  loading: boolean = true;
  private socketSub?: Subscription;

  constructor(
    private orchestratorService: OrchestratorService,
    private socketService: SocketService
  ) {}

  ngOnInit(): void {
    this.loadExceptions();
    this.socketSub = this.socketService.onEvent('project_exception').subscribe(() => {
      this.loadExceptions();
    });
  }

  ngOnDestroy(): void {
    if (this.socketSub) {
      this.socketSub.unsubscribe();
    }
  }

  loadExceptions(): void {
    this.loading = true;
    this.orchestratorService.getExceptions().subscribe({
      next: (res: any) => {
        this.exceptions = res.exceptions || [];
        this.loading = false;
      },
      error: (err) => {
        console.error('Failed to load exceptions', err);
        this.loading = false;
      }
    });
  }
}
