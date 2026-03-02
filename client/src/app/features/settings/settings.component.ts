import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { OrchestratorService, DefaultConfig } from '../../services/orchestrator.service';
import { SocketService, PullProgress } from '../../services/socket.service';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './settings.component.html',
  styleUrls: ['./settings.component.scss']
})
export class SettingsComponent implements OnInit {
  config: DefaultConfig = {
    AGENT_MODEL: '',
    OLLAMA_URL: '',
    LLM_PROVIDER: 'ollama',
    LLM_API_KEY: ''
  };

  models: string[] = [];
  isLoadingModels: boolean = true;

  pullModelName: string = '';
  isPulling: boolean = false;
  pullMsg: string = '';
  pullMsgColor: string = 'text-gray-400';
  pullProgress: number = 0;
  private pullSub: Subscription | null = null;

  saveSuccess: boolean = false;

  constructor(
    private orchestratorService: OrchestratorService,
    private socketService: SocketService
  ) {}

  ngOnInit(): void {
    this.loadSettings();
    
    // Sync initial state from service (for persistence when navigating back)
    this.isPulling = this.socketService.pullState.isPulling;
    this.pullProgress = this.socketService.pullState.progress;
    this.pullMsg = this.socketService.pullState.message;
    this.pullMsgColor = this.socketService.pullState.statusColor;

    this.pullSub = this.socketService.modelPullProgress$.subscribe({
      next: (data: PullProgress) => {
        // Just sync local state with the central service state
        this.isPulling = this.socketService.pullState.isPulling;
        this.pullProgress = this.socketService.pullState.progress;
        this.pullMsg = this.socketService.pullState.message;
        this.pullMsgColor = this.socketService.pullState.statusColor;

        if (data.status === 'success') {
          this.loadOllamaModels(data.model);
        }
      }
    });
  }

  loadSettings() {
    this.orchestratorService.getConfig().subscribe({
      next: (cfg) => {
        this.config = cfg;
        this.loadOllamaModels(cfg.AGENT_MODEL);
      },
      error: (err: any) => console.error("Failed to load config", err)
    });
  }

  loadOllamaModels(selectedModel?: string) {
    this.isLoadingModels = true;
    this.orchestratorService.getOllamaModels().subscribe({
      next: (res) => {
        this.models = res.models || [];
        this.isLoadingModels = false;
        
        const currentVal = selectedModel || this.config.AGENT_MODEL;
        if (currentVal && this.models.includes(currentVal)) {
          this.config.AGENT_MODEL = currentVal;
        } else if (this.models.length > 0) {
          this.config.AGENT_MODEL = this.models[0];
        } else {
          this.config.AGENT_MODEL = '';
        }
      },
      error: (err: any) => {
        console.error("Failed to load models list", err);
        this.isLoadingModels = false;
      }
    });
  }

  pullOllamaModel() {
    const modelToPull = this.pullModelName.trim();
    if (!modelToPull || this.isPulling) return;

    // Optimization: In cloud mode, we don't 'pull' the model, we just select it.
    if (this.config.LLM_PROVIDER === 'ollama-cloud') {
      this.config.AGENT_MODEL = modelToPull;
      this.pullMsg = `Cloud model '${modelToPull}' selected. Ready to use.`;
      this.pullMsgColor = 'text-green-400';
      this.saveConfig(); // Persist immediately
      return;
    }

    this.socketService.setPulling(modelToPull);
    // Refresh local flags from service
    this.isPulling = this.socketService.pullState.isPulling;
    this.pullProgress = this.socketService.pullState.progress;
    this.pullMsg = this.socketService.pullState.message;
    this.pullMsgColor = this.socketService.pullState.statusColor;

    this.orchestratorService.pullOllamaModel(modelToPull).subscribe({
      next: (res: any) => {
        // Signal sent to backend
      },
      error: (err: any) => {
        this.pullMsgColor = 'text-red-500';
        this.pullMsg = `Error: ${err.error?.detail || err.error?.error || err.message}`;
        this.isPulling = false;
        // Also update service state so other components know it failed
        this.socketService.pullState.isPulling = false;
      }
    });
  }

  ngOnDestroy(): void {
    if (this.pullSub) {
      this.pullSub.unsubscribe();
    }
  }

  saveConfig() {
    this.orchestratorService.saveConfig(this.config).subscribe({
      next: (res) => {
        this.saveSuccess = true;
        setTimeout(() => this.saveSuccess = false, 3000);
      },
      error: (err: any) => {
        console.error('Failed to save config', err);
        alert('Failed to save configuration.');
      }
    });
  }
}
