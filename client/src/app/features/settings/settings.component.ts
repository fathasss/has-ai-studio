import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { OrchestratorService, DefaultConfig } from '../../services/orchestrator.service';

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
    LLM_PROVIDER: 'ollama'
  };

  models: string[] = [];
  isLoadingModels: boolean = true;

  pullModelName: string = '';
  isPulling: boolean = false;
  pullMsg: string = '';
  pullMsgColor: string = 'text-gray-400';

  saveSuccess: boolean = false;

  constructor(private orchestratorService: OrchestratorService) {}

  ngOnInit(): void {
    this.loadSettings();
  }

  loadSettings() {
    this.orchestratorService.getConfig().subscribe({
      next: (cfg) => {
        this.config = cfg;
        this.loadOllamaModels(cfg.AGENT_MODEL);
      },
      error: (err) => console.error("Failed to load config", err)
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
      error: (err) => {
        console.error("Failed to load models list", err);
        this.isLoadingModels = false;
      }
    });
  }

  pullOllamaModel() {
    const modelToPull = this.pullModelName.trim();
    if (!modelToPull || this.isPulling) return;

    this.isPulling = true;
    this.pullMsgColor = 'text-blue-400';
    this.pullMsg = `Pulling ${modelToPull}, this may take several minutes depending on model size and internet speed...`;

    this.orchestratorService.pullOllamaModel(modelToPull).subscribe({
      next: (res) => {
        this.pullMsgColor = 'text-green-500';
        this.pullMsg = `Success: ${res.message || 'Model downloaded!'}`;
        this.pullModelName = '';
        this.isPulling = false;
        this.loadOllamaModels(modelToPull);
      },
      error: (err) => {
        this.pullMsgColor = 'text-red-500';
        this.pullMsg = `Error: ${err.error?.detail || err.error?.error || err.message}`;
        this.isPulling = false;
      }
    });
  }

  saveConfig() {
    this.orchestratorService.saveConfig(this.config).subscribe({
      next: (res) => {
        this.saveSuccess = true;
        setTimeout(() => this.saveSuccess = false, 3000);
      },
      error: (err) => {
        console.error('Failed to save config', err);
        alert('Failed to save configuration.');
      }
    });
  }
}
