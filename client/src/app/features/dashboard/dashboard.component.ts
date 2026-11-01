import { Component, ElementRef, ViewChild, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { OrchestratorService } from '../../services/orchestrator.service';
import { SocketService } from '../../services/socket.service';
import { marked } from 'marked';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { Subscription } from 'rxjs';

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
    { role: 'TeamLead', content: 'TeamLead devrede. Mimari orkestrasyon hattı hazır ve dinlemede.\n\nYeni proje gereksinimlerinizi bekliyorum, PO.' }
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
  public renderedPlanMd: SafeHtml | '' = '';
  public refreshingPlan: boolean = false;
  public executionStatus: string = '';
  public latestTeamLeadMessage: SafeHtml | null = null;

  private chatSubscription?: Subscription;

  constructor(
    private orchestratorService: OrchestratorService, 
    private socketService: SocketService,
    private router: Router,
    private sanitizer: DomSanitizer
  ) {
  }

  ngOnInit() {
    this.loadSessions();
    this.restoreState();
    
    // Subscribe to real-time chat messages (like TeamLead final status reports)
    this.chatSubscription = this.socketService.onEvent('new_chat_message').subscribe((msg: any) => {
      if (msg.sprint_id === this.currentSprintId && msg.role !== 'user') {
        const assistantRole = 'TeamLead'; // Normalize role display
        
        // DÜZELTME: Sohbet balonunda JSON planlarını gizle, sadece metni göster
        const rawContent = msg.content || '';
        const cleanContent = rawContent.replace(/```json[\s\S]*?```/i, '').trim();
        const displayContent = cleanContent || rawContent;

        // DÜZELTME 6: Mükerrer mesaj koruması — son mesajla aynı içeriği tekrar ekleme.
        // saveChatMessage() -> Socket.IO new_chat_message döngüsünde duplikasyon önlenir.
        const lastMsg = this.chatHistory.length > 0
          ? this.chatHistory[this.chatHistory.length - 1]
          : null;
        if (lastMsg && lastMsg.role === assistantRole && lastMsg.content === displayContent) {
          return; // Mükerrer mesajı atla
        }

        this.chatHistory.push({ role: assistantRole, content: displayContent });
        this.rawAgentHistory.push({ role: 'assistant', content: rawContent });
        
        this.syncState();
        setTimeout(() => this.scrollToBottom(), 100);
        
        // Modal update logic
        this.latestTeamLeadMessage = this.renderMarkdown(displayContent);
        
        // Clear pending execution if it's a completion or blocker message
        if (rawContent.includes('### STATUS:')) {
          this.hasPendingPlan = false; 
        }
      }
    });
  }

  ngOnDestroy() {
    if (this.chatSubscription) {
      this.chatSubscription.unsubscribe();
    }
    this.syncState();
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
      if (msgs.length > 0) {
        this.chatHistory = msgs.map(m => {
          const isTL = m.role === 'TeamLead' || m.role === 'assistant';
          const rawContent = m.content || '';
          const cleanContent = isTL ? (rawContent.replace(/```json[\s\S]*?```/i, '').trim() || rawContent) : rawContent;
          return {
            role: isTL ? 'TeamLead' : 'PO',
            content: cleanContent
          };
        });
      } else {
        this.chatHistory = [
          { role: 'TeamLead', content: `Loading history for project: ${sid}...` }
        ];
      }
      
      // Modal için son mesajı yakala
      const lastTL = [...this.chatHistory].reverse().find(m => m.role === 'TeamLead');
      if (lastTL) {
        this.latestTeamLeadMessage = this.renderMarkdown(lastTL.content);
      } else {
        this.latestTeamLeadMessage = null;
      }

      // Sync rawAgentHistory for next LLM calls
      this.rawAgentHistory = msgs.map(m => ({
        role: (m.role === 'TeamLead' || m.role === 'assistant') ? 'assistant' : 'user',
        content: m.content
      }));

      // Geçmişteki mesajlarda kayıtlı mimari plan var mı tara
      let foundPlan = false;
      for (let i = msgs.length - 1; i >= 0; i--) {
        const m = msgs[i];
        if (m.role === 'TeamLead' || m.role === 'assistant') {
          const jsonStr = this.extractJson(m.content);
          if (jsonStr) {
            try {
              this.parsedPlan = JSON.parse(jsonStr);
              let mdContent = this.parsedPlan.implementation_plan_md || '';
              if (!mdContent) {
                mdContent = m.content.replace(/```json[\s\S]*?```/i, '').trim();
              }
              if (mdContent) {
                const htmlValue = marked.parse(mdContent) as string;
                this.renderedPlanMd = this.sanitizer.bypassSecurityTrustHtml(htmlValue);
              }
              this.hasPendingPlan = true;
              foundPlan = true;
              break;
            } catch (e) {}
          }
        }
      }
      if (!foundPlan) {
        this.hasPendingPlan = false;
        this.parsedPlan = null;
        this.renderedPlanMd = '';
      }

      this.syncState();
      setTimeout(() => this.scrollToBottom(), 50);
    });
  }

  generateSprintId() {
    this.currentSprintId = "SPRINT-" + Math.floor(Math.random() * 90000 + 10000);
  }

  resetEnvironment() {
    this.chatHistory = [{ role: 'TeamLead', content: 'Ortam sıfırlandı. Yeni proje gereksinimlerinizi bekliyorum, PO.' }];
    this.rawAgentHistory = [];
    this.hasPendingPlan = false;
    this.parsedPlan = null;
    this.renderedPlanMd = '';
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

  isApprovalText(text: string): boolean {
    const clean = text.toLowerCase().trim().replace(/[.,!?;:]/g, '');
    const approvalWords = [
      'onayliyorum', 'onaylıyorum', 'onayla', 'onay',
      'evet', 'baslat', 'başlat', 'tamam', 'tamamdir', 'tamamdır',
      'uygun', 'devam et', 'devam', 'lets go', "let's go",
      'approved', 'approve', 'looks good', 'harika', 'kabul', 'start'
    ];
    return approvalWords.some(w => clean === w || clean.startsWith(w + ' ') || clean.endsWith(' ' + w));
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

    // Direct approval intercept: if user typed "onaylıyorum" / "başlat" etc.
    if (this.isApprovalText(userText) && (this.hasPendingPlan || this.chatHistory.length > 1)) {
      this.chatHistory.push({ role: 'PO', content: userText });
      this.rawAgentHistory.push({ role: 'user', content: userText });
      this.orchestratorService.saveChatMessage(this.currentSprintId, 'user', userText).subscribe();

      const tlMsg = "🚀 Harika! Proje onaylandı. Ekip projenin gereksinimlerine göre yapılandırılan dinamik fazlar doğrultusunda geliştirmeye başlıyor. 3D Ofis ortamına aktarılıyorsunuz...";
      this.chatHistory.push({ role: 'TeamLead', content: tlMsg });
      this.rawAgentHistory.push({ role: 'assistant', content: tlMsg });
      this.orchestratorService.saveChatMessage(this.currentSprintId, 'TeamLead', tlMsg).subscribe();
      this.syncState();
      setTimeout(() => this.scrollToBottom(), 50);

      this.buildAndExecuteDirectly();
      return;
    }
    
    this.chatHistory.push({ role: 'PO', content: userText });
    this.rawAgentHistory.push({ role: 'user', content: userText });
    this.syncState();
    setTimeout(() => this.scrollToBottom(), 50);
    
    // Save User message
    this.orchestratorService.saveChatMessage(this.currentSprintId, 'user', userText).subscribe();

    this.isTyping = true;

    this.orchestratorService.chatTeamLead(this.rawAgentHistory).subscribe({
      next: (res) => {
        const rawResponse = res.response;
        const cleanContent = rawResponse.replace(/```json[\s\S]*?```/i, '').trim();
        const displayContent = cleanContent || rawResponse;

        // Anında sohbet geçmişine ekle (kullanıcı hemen görsün, soket gecikmesinden etkilenmesin)
        const lastMsg = this.chatHistory.length > 0 ? this.chatHistory[this.chatHistory.length - 1] : null;
        if (!lastMsg || lastMsg.role !== 'TeamLead' || lastMsg.content !== displayContent) {
          this.chatHistory.push({ role: 'TeamLead', content: displayContent });
          this.rawAgentHistory.push({ role: 'assistant', content: rawResponse });
        }
        this.latestTeamLeadMessage = this.renderMarkdown(displayContent);
        this.syncState();
        setTimeout(() => this.scrollToBottom(), 50);
        
        // Backend'e kaydet ve oturum listesini tazele
        this.orchestratorService.saveChatMessage(this.currentSprintId, 'TeamLead', rawResponse).subscribe(() => {
          this.loadSessions(); 
        });

        this.isTyping = false;
        
        // Plan kontrolü (Gerekirse silent refresh tetikle)
        const contentLower = rawResponse.toLowerCase();
        const triggerKeywords = ['plan', 'architecture', 'mimari', 'tasarım', 'structure', 'blueprint', 'şema', 'hazırl', 'oluştur', 'hazır', 'analiz', 'preview', 'onay', 'faz'];
        const hasTriggerWord = triggerKeywords.some(word => contentLower.includes(word));
        const hasStructuralMarker = rawResponse.includes('##') || rawResponse.includes('###');

        if (this.hasPendingPlan || hasTriggerWord || hasStructuralMarker) {
          this.hasPendingPlan = true;
          this.refreshPlan(true); 
        }
      },
      error: (err) => {
        this.chatHistory.push({ role: 'TeamLead', content: '[Bağlantı Hatası] Orkestratöre ulaşılamadı. Lütfen servisi kontrol edin.' });
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
          } else {
            this.renderedPlanMd = '';
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
      error: (err: any) => {
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

    if (this.parsedPlan && this.parsedPlan.tasks && this.parsedPlan.tasks.length > 0) {
      this.approveSprint();
      return;
    }

    // rawAgentHistory boşsa chatHistory'den yeniden oluştur
    if (this.rawAgentHistory.length === 0 && this.chatHistory.length > 0) {
      this.rawAgentHistory = this.chatHistory.map(m => ({
        role: m.role === 'TeamLead' ? 'assistant' : 'user',
        content: m.content
      }));
    }
    
    this.isLoadingPlan = true;
    this.planError = '';
    this.executionStatus = 'Plan hazırlanıyor...';
    
    this.orchestratorService.previewSprint(this.rawAgentHistory).subscribe({
      next: (res: any) => {
        try {
          const jsonStr = this.extractJson(res.response);
          if (!jsonStr) throw new Error("TeamLead yanıtında mimari plan JSON yapısı bulunamadı. Lütfen tekrar deneyin.");
          
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
      error: (err: any) => {
        console.error("Preview call failed:", err);
        this.planError = err.message || "TeamLead'e ulaşılamadı. Bağlantınızı kontrol edin.";
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
      const slug = this.slugify(this.parsedPlan.project_name);
      if (slug) {
        this.currentSprintId = slug;
      }
    }

    const execute = () => {
      this.closePreviewModal();
      this.hasPendingPlan = false;
      
      this.executionStatus = 'Ajanlar başlatılıyor...';
      this.orchestratorService.executeSprint(this.currentSprintId, this.parsedPlan, this.rawAgentHistory).subscribe({
        next: () => {
          this.isLoadingPlan = false;
          this.executionStatus = '';
          this.router.navigate(['/active-projects'], { queryParams: { sprint: this.currentSprintId } });
        },
        error: (err) => {
          console.error("Sprint execution failed", err);
          this.planError = "Çalıştırma hatası: " + (err.message || "Bilinmeyen hata");
          this.isLoadingPlan = false;
          this.executionStatus = '';
          this.showPreviewModal = true;
        }
      });
      
      this.syncState();
    };

    if (oldId && oldId !== this.currentSprintId) {
      this.executionStatus = 'Oturum taşınıyor...';
      this.orchestratorService.migrateChatHistory(oldId, this.currentSprintId).subscribe({
        next: () => execute(),
        error: (err) => {
          console.warn("Migration warning, proceeding to execute anyway:", err);
          execute();
        }
      });
    } else {
      execute();
    }
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
    
    // Try to find ALL markdown blocks (allowing any language tag like python, bash, json etc)
    const mdRegex = /```[a-z0-9]*\s*([\s\S]*?)```/gi;
    let match;
    const candidates: string[] = [];

    while ((match = mdRegex.exec(text)) !== null) {
      candidates.push(match[1].trim());
    }

    if (candidates.length === 0) {
      // Fallback: Find the first '{' and its matching '}'
      const startIdx = text.indexOf('{');
      if (startIdx !== -1) {
        let braceCount = 0;
        let inString = false;
        let escaped = false;
        let foundEnd = false;
        let candidateStr = '';

        for (let i = startIdx; i < text.length; i++) {
          const char = text[i];
          if (inString) {
            if (escaped) escaped = false;
            else if (char === '\\') escaped = true;
            else if (char === '"') inString = false;
          } else {
            if (char === '"') inString = true;
            else if (char === '{') braceCount++;
            else if (char === '}') {
              braceCount--;
              if (braceCount === 0) {
                candidateStr = text.substring(startIdx, i + 1);
                foundEnd = true;
                break;
              }
            }
          }
        }
        if (foundEnd) candidates.push(candidateStr);
      }
    }

    // Evaluate candidates to find the most likely JSON plan
    for (const rawCandidate of candidates) {
      try {
        const cleaned = this.robustCleanJson(rawCandidate);
        
        // Try parsing directly
        let parsed: any = null;
        try {
          parsed = JSON.parse(cleaned);
        } catch (e) {
          const sIdx = cleaned.indexOf('{');
          if (sIdx !== -1) {
             let balance = 0;
             let inStr = false;
             for (let i = sIdx; i < cleaned.length; i++) {
                if (cleaned[i] === '"' && cleaned[i-1] !== '\\') inStr = !inStr;
                if (!inStr) {
                   if (cleaned[i] === '{') balance++;
                   if (cleaned[i] === '}') {
                      balance--;
                      if (balance === 0) {
                         const innerJson = cleaned.substring(sIdx, i + 1);
                         parsed = JSON.parse(innerJson);
                         break;
                      }
                   }
                }
             }
          }
        }
        
        if (parsed && (parsed.tasks || parsed.project_name)) {
          return JSON.stringify(parsed); // Return re-serialized clean JSON
        }
      } catch (e) {
        // Continue searching
      }
    }
    
    return null;
  }

  private robustCleanJson(rawCandidate: string): string {
    let cleaned = '';
    let inString = false;
    let escaped = false;
    
    for (let i = 0; i < rawCandidate.length; i++) {
        const char = rawCandidate[i];
        
        if (inString) {
            if (escaped) {
                cleaned += char;
                escaped = false;
            } else if (char === '\\') {
                const next = rawCandidate[i+1];
                if (next && '\"\\\/bfnrtu'.includes(next)) {
                    cleaned += char;
                    escaped = true;
                } else {
                    cleaned += '\\\\';
                }
            } else if (char === '\"') {
                inString = false;
                cleaned += char;
            } else {
                const code = char.charCodeAt(0);
                if (code < 32) {
                    if (char === '\n') cleaned += '\\n';
                    else if (char === '\r') cleaned += '\\r';
                    else if (char === '\t') cleaned += '\\t';
                    else cleaned += '\\u' + code.toString(16).padStart(4, '0');
                } else {
                    cleaned += char;
                }
            }
        } else {
            if (char === '\"') {
                inString = true;
                cleaned += char;
            } else {
                cleaned += char;
            }
        }
    }
    
    return cleaned.replace(/,\s*}/g, '}').replace(/,\s*]/g, ']');
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

}
