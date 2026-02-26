import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { SocketService } from '../../../services/socket.service';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './sidebar.component.html',
  styleUrls: ['./sidebar.component.scss']
})
export class SidebarComponent implements OnInit, OnDestroy {
  public ramUsage: number = 0;
  public cpuUsage: number = 0;
  public diskUsage: number = 0;
  public gpuUsage: number = 0;
  public uptimeString: string = '00:00:00';
  public tokensMin: number = 0;
  private sub: Subscription | null = null;

  constructor(private socketService: SocketService) {}

  ngOnInit(): void {
    this.sub = this.socketService.systemUpdate$.subscribe({
      next: (res: any) => {
         if (res) {
           this.ramUsage = Math.round(res.ram) || 0;
           this.cpuUsage = Math.round(res.cpu) || 0;
           this.diskUsage = Math.round(res.disk) || 0;
           this.gpuUsage = Math.round(res.gpu) || 0;
           this.tokensMin = res.tokens_min || 0;
           
           if (res.uptime !== undefined) {
             this.uptimeString = this.formatUptime(res.uptime);
           }
         }
      },
      error: (err) => console.error("Error receiving system status", err)
    });
  }

  private formatUptime(totalSec: number): string {
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = Math.floor(totalSec % 60);
    return [h, m, s].map(v => v < 10 ? '0' + v : v).join(':');
  }

  ngOnDestroy(): void {
    if (this.sub) {
      this.sub.unsubscribe();
    }
  }
}
