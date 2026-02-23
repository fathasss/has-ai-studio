import { Component, ElementRef, ViewChild, AfterViewChecked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { OrchestratorService } from '../../services/orchestrator.service';

interface ChatMessage {
  role: 'TeamLead' | 'PO';
  content: string;
}

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss']
})
export class DashboardComponent implements AfterViewChecked {
  @ViewChild('chatContainer') private chatContainer!: ElementRef;
  
  public currentSprintIdLabel: string = "";
  public currentSprintId: string = "";
  
  public prompt: string = '';
  public chatHistory: ChatMessage[] = [
    { role: 'TeamLead', content: 'TeamLead initialized. Factory environment is secured and sequential orchestration bridge is hot-loaded.\n\nAwaiting your project requirements, PO.' }
  ];
  
  public rawAgentHistory: any[] = []; // for backend
  
  public isTyping: boolean = false;
  public hasPendingPlan: boolean = false;
  
  // Modal State
  public showPreviewModal: boolean = false;
  public isLoadingPlan: boolean = false;
  public parsedPlan: any = null;
  public planError: string = '';

  constructor(private orchestratorService: OrchestratorService, private router: Router) {
    this.generateSprintId();
  }

  ngAfterViewChecked() {
    this.scrollToBottom();
  }

  generateSprintId() {
    this.currentSprintId = "SPRINT-" + Math.floor(Math.random() * 90000 + 10000);
  }

  resetEnvironment() {
    this.chatHistory = [{ role: 'TeamLead', content: 'Environment Reset. Awaiting your project requirements, PO.' }];
    this.rawAgentHistory = [];
    this.hasPendingPlan = false;
    this.generateSprintId();
  }

  scrollToBottom(): void {
    try {
      this.chatContainer.nativeElement.scrollTop = this.chatContainer.nativeElement.scrollHeight;
    } catch(err) { }
  }

  sendMessage() {
    if (!this.prompt.trim() || this.isTyping) return;
    
    const userText = this.prompt.trim();
    this.prompt = '';
    
    this.chatHistory.push({ role: 'PO', content: userText });
    this.rawAgentHistory.push({ role: 'user', content: userText });
    this.isTyping = true;
    this.hasPendingPlan = false;

    this.orchestratorService.chatTeamLead(this.rawAgentHistory).subscribe({
      next: (res) => {
        this.chatHistory.push({ role: 'TeamLead', content: res.response });
        this.rawAgentHistory.push({ role: 'assistant', content: res.response });
        this.isTyping = false;
        this.hasPendingPlan = true;
      },
      error: (err) => {
        this.chatHistory.push({ role: 'TeamLead', content: '[Connection Error] Could not reach orchestrator.' });
        this.isTyping = false;
      }
    });
  }

  previewPlan() {
    this.showPreviewModal = true;
    this.isLoadingPlan = true;
    this.planError = '';
    this.parsedPlan = null;
    
    this.orchestratorService.previewSprint(this.rawAgentHistory).subscribe({
      next: (res) => {
        try {
          const match = res.response.match(/\{[\s\S]*\}/);
          if (!match) throw new Error("Could not parse JSON from TeamLead.");
          this.parsedPlan = JSON.parse(match[0]);
          this.isLoadingPlan = false;
        } catch (e: any) {
          this.planError = e.message;
          this.isLoadingPlan = false;
        }
      },
      error: (err) => {
        this.planError = err.message || "Failed to load preview";
        this.isLoadingPlan = false;
      }
    });
  }

  closePreviewModal() {
    this.showPreviewModal = false;
  }

  approveSprint() {
    if (!this.parsedPlan) return;
    
    this.closePreviewModal();
    this.hasPendingPlan = false;
    
    const tlMsg = `Sprint Authorized from Preview. Locking in architecture for project: ${this.parsedPlan.project_name || 'unknown'}. Execution starting...`;
    this.chatHistory.push({ role: 'TeamLead', content: tlMsg });
    
    this.orchestratorService.executeSprint(this.currentSprintId, this.parsedPlan, this.rawAgentHistory).subscribe({
      next: (res) => {
        setTimeout(() => {
          // Sprint başlatılınca projeler ekranına yönlendir 
          this.router.navigate(['/active-projects']);
        }, 1500);
      },
      error: (err) => console.error("Sprint execution failed", err)
    });
  }
}
