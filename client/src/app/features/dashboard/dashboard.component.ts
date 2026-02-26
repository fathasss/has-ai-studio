import { Component, ElementRef, ViewChild, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { OrchestratorService } from '../../services/orchestrator.service';
import { marked } from 'marked';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

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
export class DashboardComponent implements OnInit, OnDestroy {
  @ViewChild('chatContainer') private chatContainer!: ElementRef;
  @ViewChild('promptInput') private promptInput!: ElementRef;
  
  public currentSprintIdLabel: string = "";
  public currentSprintId: string = "";
  
  public prompt: string = '';
  public chatHistory: ChatMessage[] = [
    { role: 'TeamLead', content: 'TeamLead initialized. Factory environment is secured and sequential orchestration bridge is hot-loaded.\n\nAwaiting your project requirements, PO.' }
  ];
  
  public rawAgentHistory: any[] = []; // for backend
  
  public isTyping: boolean = false;
  public hasPendingPlan: boolean = false;
  
  public chatSessions: {id: string, name: string}[] = [];
  public selectedSession: string | null = null;
  
  // Modal State
  public showPreviewModal: boolean = false;
  public isLoadingPlan: boolean = false;
  public parsedPlan: any = null;
  public planError: string = '';
  public renderedPlanMd: SafeHtml = '';
  public refreshingPlan: boolean = false;
  public executionStatus: string = '';
  public latestTeamLeadMessage: SafeHtml | null = null;

  constructor(
    private orchestratorService: OrchestratorService, 
    private router: Router,
    private sanitizer: DomSanitizer
  ) {
  }

  ngOnInit() {
    this.loadSessions();
    this.restoreState();
  }

  restoreState() {
    const saved = this.orchestratorService.chatState;
    if (saved) {
      this.currentSprintId = saved.currentSprintId;
      this.chatHistory = saved.chatHistory;
      this.rawAgentHistory = saved.rawAgentHistory;
      this.selectedSession = saved.selectedSession;
      this.isTyping = saved.isTyping;
      this.hasPendingPlan = saved.hasPendingPlan;
      this.prompt = saved.draftPrompt;
    } else {
      this.generateSprintId();
      this.syncState();
    }
  }

  syncState() {
    this.orchestratorService.chatState = {
      currentSprintId: this.currentSprintId,
      chatHistory: this.chatHistory,
      rawAgentHistory: this.rawAgentHistory,
      selectedSession: this.selectedSession,
      isTyping: this.isTyping,
      hasPendingPlan: this.hasPendingPlan,
      draftPrompt: this.prompt
    };
  }

  loadSessions() {
    this.orchestratorService.getChatSessions().subscribe(res => {
      this.chatSessions = res.sessions;
    });
  }

  loadHistory(sid: string) {
    this.selectedSession = sid;
    this.currentSprintId = sid;
    this.orchestratorService.getChatHistory(sid).subscribe(msgs => {
      this.chatHistory = msgs.length > 0 ? msgs : [
        { role: 'TeamLead', content: `Loading history for project: ${sid}...` }
      ];
      
      // Modal için son mesajı yakala
      const lastTL = [...msgs].reverse().find(m => m.role === 'TeamLead');
      if (lastTL) {
        this.latestTeamLeadMessage = this.renderMarkdown(lastTL.content);
      } else {
        this.latestTeamLeadMessage = null;
      }

      // Sync rawAgentHistory for next LLM calls
      this.rawAgentHistory = msgs.map(m => ({
        role: m.role === 'TeamLead' ? 'assistant' : 'user',
        content: m.content
      }));
      this.syncState();
      setTimeout(() => this.scrollToBottom(), 50);
    });
  }

  generateSprintId() {
    this.currentSprintId = "SPRINT-" + Math.floor(Math.random() * 90000 + 10000);
  }

  resetEnvironment() {
    this.chatHistory = [{ role: 'TeamLead', content: 'Environment Reset. Awaiting your project requirements, PO.' }];
    this.rawAgentHistory = [];
    this.hasPendingPlan = false;
    this.selectedSession = null;
    this.generateSprintId();
    this.loadSessions();
    this.syncState();
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
    
    // Snaps back to original height immediately
    if (this.promptInput) {
      const textarea = this.promptInput.nativeElement;
      textarea.style.height = '48px';
    }
    
    this.chatHistory.push({ role: 'PO', content: userText });
    this.rawAgentHistory.push({ role: 'user', content: userText });
    this.syncState();
    setTimeout(() => this.scrollToBottom(), 50);
    
    // Save User message
    this.orchestratorService.saveChatMessage(this.currentSprintId, 'user', userText).subscribe();

    this.isTyping = true;
    // this.hasPendingPlan = false; // REMOVED: Keep the state so refinements can happen silently

    this.orchestratorService.chatTeamLead(this.rawAgentHistory).subscribe({
      next: (res) => {
        const rawResponse = res.response;
        // Metin içindeki JSON bloğunu sohbetten gizlemek için filtrele
        const cleanResponse = rawResponse.replace(/```json[\s\S]*?```/i, '').trim();
        
        const assistantContent = cleanResponse || rawResponse;
        
        // Modal için son mesajı sakla
        this.latestTeamLeadMessage = this.renderMarkdown(assistantContent);

        this.chatHistory.push({ role: 'TeamLead', content: assistantContent });
        this.rawAgentHistory.push({ role: 'assistant', content: rawResponse });
        this.syncState();
        setTimeout(() => this.scrollToBottom(), 50);
        
        // Save Assistant message
        this.orchestratorService.saveChatMessage(this.currentSprintId, 'TeamLead', rawResponse).subscribe(() => {
          this.loadSessions(); // Update sessions list in case it's a new one
        });

        this.isTyping = false;
        
        // If we already have a plan, or if the user is in the "planning" phase, refresh it
        const contentLower = assistantContent.toLowerCase();
        const triggerKeywords = ['plan', 'architecture', 'mimari', 'tasarım', 'structure', 'blueprint', 'şema', 'hazırl', 'oluştur', 'hazır', 'analiz', 'preview'];
        const hasTriggerWord = triggerKeywords.some(word => contentLower.includes(word));
        const hasStructuralMarker = assistantContent.includes('##') || assistantContent.includes('###');

        if (this.hasPendingPlan || hasTriggerWord || hasStructuralMarker) {
          this.hasPendingPlan = true;
          this.refreshPlan(true); 
        }
      },
      error: (err) => {
        this.chatHistory.push({ role: 'TeamLead', content: '[Connection Error] Could not reach orchestrator.' });
        this.isTyping = false;
      }
    });
  }

  previewPlan() {
    this.showPreviewModal = true;
    this.refreshPlan(false);
  }

  refreshPlan(isSilent: boolean = false) {
    if (!isSilent) {
      this.isLoadingPlan = true;
    } else {
      this.refreshingPlan = true;
    }
    
    this.planError = '';
    
    this.orchestratorService.previewSprint(this.rawAgentHistory).subscribe({
      next: (res) => {
        try {
          const jsonStr = this.extractJson(res.response);
          if (!jsonStr) throw new Error("TeamLead'den uygun formatta JSON bloğu alınamadı.");
          
          this.parsedPlan = JSON.parse(jsonStr);
          
          // Eğer JSON içinde MD planı varsa onu kullan, yoksa JSON dışındaki metni MD olarak al
          let mdContent = this.parsedPlan.implementation_plan_md || '';
          if (!mdContent) {
            mdContent = res.response.replace(/```json[\s\S]*?```/i, '').trim();
          }

          if (mdContent) {
            const htmlValue = marked.parse(mdContent) as string;
            this.renderedPlanMd = this.sanitizer.bypassSecurityTrustHtml(htmlValue);
          }

          this.isLoadingPlan = false;
          this.refreshingPlan = false;
        } catch (e: any) {
          console.error("Plan parsing error:", e);
          if (!isSilent) this.planError = e.message;
          this.isLoadingPlan = false;
          this.refreshingPlan = false;
        }
      },
      error: (err) => {
        if (!isSilent) this.planError = err.message || "Failed to load preview";
        this.isLoadingPlan = false;
        this.refreshingPlan = false;
      }
    });
  }

  closePreviewModal() {
    this.showPreviewModal = false;
  }

  buildAndExecuteDirectly() {
    if (this.isLoadingPlan) return;
    
    this.isLoadingPlan = true;
    this.planError = '';
    this.executionStatus = 'Preparing plan...';
    
    this.orchestratorService.previewSprint(this.rawAgentHistory).subscribe({
      next: (res) => {
        try {
          const jsonStr = this.extractJson(res.response);
          if (!jsonStr) throw new Error("JSON not found in TeamLead response. Try again or check the requirements.");
          
          this.parsedPlan = JSON.parse(jsonStr);
          
          // Execute immediately
          this.approveSprint();
        } catch (e: any) {
          console.error("Plan parsing error:", e);
          this.planError = e.message;
          this.isLoadingPlan = false;
          this.executionStatus = '';
          this.showPreviewModal = true; 
        }
      },
      error: (err) => {
        console.error("Preview call failed:", err);
        this.planError = err.message || "Failed to reach TeamLead. Check your connection.";
        this.isLoadingPlan = false;
        this.executionStatus = '';
        this.showPreviewModal = true;
      }
    });
  }

  approveSprint() {
    if (!this.parsedPlan) return;
    
    const oldId = this.currentSprintId;
    if (this.parsedPlan.project_name) {
      this.currentSprintId = this.slugify(this.parsedPlan.project_name);
    }

    this.executionStatus = 'Migrating session...';
    this.orchestratorService.migrateChatHistory(oldId, this.currentSprintId).subscribe({
      next: () => {
        this.closePreviewModal();
        this.hasPendingPlan = false;
        
        this.executionStatus = 'Starting workforce...';
        this.orchestratorService.executeSprint(this.currentSprintId, this.parsedPlan, this.rawAgentHistory).subscribe({
          next: () => {
            this.isLoadingPlan = false;
            this.executionStatus = '';
            this.router.navigate(['/active-projects']);
          },
          error: (err) => {
            console.error("Sprint execution failed", err);
            this.planError = "Execution failed: " + (err.message || "Unknown error");
            this.isLoadingPlan = false;
            this.executionStatus = '';
            this.showPreviewModal = true;
          }
        });
        
        this.syncState();
      },
      error: (err) => {
        console.error("Migration failed", err);
        this.planError = "Migration failed: " + (err.message || "Unknown error");
        this.isLoadingPlan = false;
        this.executionStatus = '';
        this.showPreviewModal = true;
      }
    });
  }

  private slugify(text: string): string {
    return text
      .toString()
      .normalize('NFD')                   // Handle accented characters (Turkish ş, ı, etc.)
      .replace(/[\u0300-\u036f]/g, '')    // Strip markers
      .toLowerCase()
      .trim()
      .replace(/\s+/g, '-')           // Replace spaces with -
      .replace(/[^\w\-]+/g, '')       // Remove all non-word chars
      .replace(/\-\-+/g, '-')         // Replace multiple - with single -
      .replace(/^-+/, '')             // Trim - from start of text
      .replace(/-+$/, '');            // Trim - from end of text
  }

  public renderMarkdown(text: string): SafeHtml {
    if (!text) return '';
    try {
      const html = marked.parse(text) as string;
      return this.sanitizer.bypassSecurityTrustHtml(html);
    } catch(e) {
      return text;
    }
  }

  private extractJson(text: string): string | null {
    if (!text) return null;
    const startIdx = text.indexOf('{');
    const endIdx = text.lastIndexOf('}');
    if (startIdx !== -1 && endIdx !== -1 && endIdx > startIdx) {
      let candidate = text.substring(startIdx, endIdx + 1);
      // Basic cleanup for common LLM artifacts
      candidate = candidate.replace(/,\s*}/g, '}').replace(/,\s*]/g, ']');
      return candidate;
    }
    return null;
  }

  onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }

  adjustTextareaHeight() {
    if (!this.promptInput) return;
    const textarea = this.promptInput.nativeElement;
    
    // Aggressive reset and measure
    textarea.style.height = '48px'; 
    const newHeight = textarea.scrollHeight;
    
    if (newHeight > 48) {
      textarea.style.height = newHeight + 'px';
    } else {
      textarea.style.height = '48px';
    }
    
    this.scrollToBottom();
  }

  ngOnDestroy() {
    this.syncState();
  }
}
