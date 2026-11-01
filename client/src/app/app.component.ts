import { Component, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { CommonModule } from '@angular/common';
import { SidebarComponent } from './core/components/sidebar/sidebar.component';
import { HeaderComponent } from './core/components/header/header.component';
import { RightPanelComponent } from './core/components/right-panel/right-panel.component';
import { SocketService } from './services/socket.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, RouterOutlet, SidebarComponent, HeaderComponent, RightPanelComponent],
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.scss']
})
export class AppComponent implements OnInit {
  title = 'client';
  rightPanelOpen: boolean = true;

  constructor(private socketService: SocketService) {}

  toggleRightPanel(): void {
    this.rightPanelOpen = !this.rightPanelOpen;
  }

  ngOnInit() {
    this.socketService.connected$.subscribe(isConnected => {
      console.log('Socket.io connected:', isConnected);
    });
  }
}
