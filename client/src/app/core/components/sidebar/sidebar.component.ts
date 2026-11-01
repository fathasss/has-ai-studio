import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { SocketService } from '../../../services/socket.service';
import { TranslatePipe } from '../../pipes/translate.pipe';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-sidebar',
  standalone: true,
  imports: [CommonModule, RouterModule, TranslatePipe],
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

  // Network Chart Stats
  public sentHistory: number[] = new Array(30).fill(0);
  public recvHistory: number[] = new Array(30).fill(0);
  public netSentSpeed: string = '0 KB/s';
  public netRecvSpeed: string = '0 KB/s';
  public polylineSent: string = '';
  public polylineRecv: string = '';
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
           
           // Network Update
           if (res.net_sent !== undefined) {
             this.updateNetworkHistory(res.net_sent, res.net_recv);
           }

           if (res.uptime !== undefined) {
             this.uptimeString = this.formatUptime(res.uptime);
           }
         }
      },
      error: (err) => console.error("Error receiving system status", err)
    });
  }

  private updateNetworkHistory(sent: number, recv: number) {
    this.netSentSpeed = this.formatBytes(sent) + '/s';
    this.netRecvSpeed = this.formatBytes(recv) + '/s';

    this.sentHistory.push(sent);
    this.recvHistory.push(recv);

    if (this.sentHistory.length > 30) this.sentHistory.shift();
    if (this.recvHistory.length > 30) this.recvHistory.shift();

    this.polylineSent = this.generatePolyline(this.sentHistory);
    this.polylineRecv = this.generatePolyline(this.recvHistory);
  }

  private generatePolyline(data: number[]): string {
    if (data.length === 0) return '';
    const max = Math.max(...data, 1024); // Min scale 1KB
    const height = 40;
    const width = 180;
    const step = width / (data.length - 1);

    return data.map((val, i) => {
      const x = i * step;
      const y = height - (val / max) * height;
      return `${x},${y}`;
    }).join(' ');
  }

  private formatBytes(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
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
