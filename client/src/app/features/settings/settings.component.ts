import { Component, OnInit, OnDestroy, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { OrchestratorService, DefaultConfig, ProviderNode } from '../../services/orchestrator.service';
import { SocketService, PullProgress } from '../../services/socket.service';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-settings',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './settings.component.html',
  styleUrls: ['./settings.component.scss']
})
export class SettingsComponent implements OnInit, OnDestroy {
  isNodeActive(node: ProviderNode): boolean {
    return this.config.ACTIVE_NODE_ID === node.id;
  }

  // Model Dropdown State
  isModelDropdownOpen = false;
  modelSearchQuery = '';

  get filteredModels(): string[] {
    if (!this.modelSearchQuery.trim()) return this.models;
    const query = this.modelSearchQuery.toLowerCase();
    return this.models.filter(m => m.toLowerCase().includes(query));
  }

  get isSelectedNodeActive(): boolean {
    return !!(this.selectedNode && this.config.ACTIVE_NODE_ID === this.selectedNode.id);
  }

  get showModelDropdown(): boolean {
    return this.isModelDropdownOpen && !this.isLoadingModels;
  }

  get showPullStatus(): boolean {
    return !!(this.pullMsg || this.isPulling);
  }

  get pullProgressMinWidth(): number {
    return this.pullProgress > 0 ? 0 : 2;
  }

  get deployButtonText(): string {
    return this.isSelectedNodeActive ? 'Cluster Deployed' : 'Deploy Cluster';
  }

  get selectedNodeId(): string | undefined {
    return this.selectedNode?.id;
  }

  toggleModelDropdown(event?: Event) {
    if (event) event.stopPropagation();
    if (this.isLoadingModels) return;
    this.isModelDropdownOpen = !this.isModelDropdownOpen;
    if (this.isModelDropdownOpen) {
      this.modelSearchQuery = '';
    }
  }

  closeModelDropdown() {
    this.isModelDropdownOpen = false;
  }

  selectModel(model: string) {
    if (this.selectedNode) {
      this.selectedNode.model = model;
      this.selectedNode.teamleadModel = model;
    }
    this.closeModelDropdown();
  }

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent) {
    const target = event.target as HTMLElement;
    if (!target.closest('.custom-model-select-container')) {
      this.closeModelDropdown();
    }
  }

  config: DefaultConfig = {
    NODES: [],
    ACTIVE_NODE_ID: ''
  };

  systemStatus: any = null;

  selectedNode: ProviderNode | null = null;
  models: string[] = [];
  isLoadingModels: boolean = false;

  // Pulling state
  pullModelName: string = '';
  isPulling: boolean = false;
  pullMsg: string = '';
  pullMsgColor: string = 'text-zinc-400';
  pullProgress: number = 0;
  private pullSub: Subscription | null = null;
  private statusTimer: any;

  saveSuccess: boolean = false;
  isAddingNode: boolean = false;

  constructor(
    private orchestratorService: OrchestratorService,
    private socketService: SocketService
  ) {}

  ngOnInit(): void {
    this.loadSettings();
    this.refreshSystemStatus();
    
    // Periodically refresh status to check installation progress
    this.statusTimer = setInterval(() => this.refreshSystemStatus(), 10000);
    
    // Sync initial state from central service
    this.isPulling = this.socketService.pullState.isPulling;
    this.pullProgress = this.socketService.pullState.progress;
    this.pullMsg = this.socketService.pullState.message;
    this.pullMsgColor = this.socketService.pullState.statusColor;

    this.pullSub = this.socketService.modelPullProgress$.subscribe({
      next: (data: PullProgress) => {
        this.isPulling = this.socketService.pullState.isPulling;
        this.pullProgress = this.socketService.pullState.progress;
        this.pullMsg = this.socketService.pullState.message;
        this.pullMsgColor = this.socketService.pullState.statusColor;

        if (data.status === 'success' && this.selectedNode) {
          this.loadOllamaModels(this.selectedNode.model);
        }
      }
    });
  }

  loadSettings() {
    this.orchestratorService.getConfig().subscribe({
      next: (cfg) => {
        this.config = cfg || { NODES: [], ACTIVE_NODE_ID: '' };
        if (!this.config.NODES) this.config.NODES = [];
        this.setActiveNodeDetails();
      },
      error: (err: any) => {
        console.error("Failed to load config", err);
        this.config = { NODES: [], ACTIVE_NODE_ID: '' };
      }
    });
  }

  refreshSystemStatus() {
    this.orchestratorService.getSystemStatus().subscribe({
      next: (status) => {
        this.systemStatus = status;
      },
      error: (err) => console.error("Failed to fetch system status", err)
    });
  }

  setActiveNodeDetails() {
    this.selectedNode = this.config.NODES.find(n => n.id === this.config.ACTIVE_NODE_ID) || this.config.NODES[0] || null;
    if (this.selectedNode) {
      this.loadOllamaModels(this.selectedNode.model);
    }
  }

  selectNode(node: ProviderNode) {
    this.selectedNode = node;
    this.loadOllamaModels(node.model);
  }

  deployNode() {
    if (!this.selectedNode) return;
    this.config.ACTIVE_NODE_ID = this.selectedNode.id;
    this.saveConfig();
  }

  onProviderChange() {
    if (this.selectedNode) {
      if (this.selectedNode.provider === 'ollama-cloud') {
        this.selectedNode.url = 'https://ollama.com';
      } else if (this.selectedNode.provider === 'ollama' && (!this.selectedNode.url || this.selectedNode.url.includes('openai') || this.selectedNode.url === 'https://ollama.com')) {
        this.selectedNode.url = 'http://has-ai-ollama:11434';
      } else if (this.selectedNode.provider === 'openai' && (!this.selectedNode.url || this.selectedNode.url.includes('ollama'))) {
        this.selectedNode.url = 'https://api.openai.com/v1';
      }
      this.loadOllamaModels(this.selectedNode.model);
    }
  }

  isManualModel: boolean = false;

  toggleManualMode() {
    this.isManualModel = !this.isManualModel;
  }

  loadOllamaModels(selectedModel?: string) {
    if (!this.selectedNode) {
      this.models = [];
      return;
    }

    this.isLoadingModels = true;
    this.models = []; // Clear existing while loading
    
    this.orchestratorService.getOllamaModels(
      this.selectedNode.url,
      this.selectedNode.provider,
      this.selectedNode.apiKey
    ).subscribe({
      next: (res) => {
        this.models = res.models || [];
        this.isLoadingModels = false;
        
        // If we have models but none selected, pick the first one as default
        if (this.models.length > 0 && !this.selectedNode?.model) {
          this.selectedNode!.model = this.models[0];
          this.selectedNode!.teamleadModel = this.models[0];
        } else if (selectedModel && this.models.includes(selectedModel)) {
          this.selectedNode!.model = selectedModel;
          this.selectedNode!.teamleadModel = selectedModel;
        }
      },
      error: (err: any) => {
        console.error("Failed to load models list", err);
        this.isLoadingModels = false;
        this.models = [];
      }
    });
  }

  startAddNode() {
    const newNode: ProviderNode = {
      id: 'node-' + Date.now(),
      name: 'New Node',
      provider: 'ollama',
      url: 'http://has-ai-ollama:11434',
      model: '',
      teamleadModel: '',
      apiKey: ''
    };
    this.config.NODES.push(newNode);
    this.selectNode(newNode);
    this.isAddingNode = true;
  }

  deleteNode(node: ProviderNode, event: Event) {
    event.stopPropagation();
    if (this.config.NODES.length <= 1) {
      alert("At least one node must remain in the configuration.");
      return;
    }
    this.config.NODES = this.config.NODES.filter(n => n.id !== node.id);
    if (this.config.ACTIVE_NODE_ID === node.id) {
      this.config.ACTIVE_NODE_ID = this.config.NODES[0].id;
    }
    if (this.selectedNode?.id === node.id) {
      this.setActiveNodeDetails();
    }
  }

  pullOllamaModel() {
    const modelToPull = this.pullModelName.trim();
    if (!modelToPull || this.isPulling || !this.selectedNode) return;

    if (this.selectedNode.provider === 'ollama-cloud') {
      this.selectedNode.model = modelToPull;
      this.selectedNode.teamleadModel = modelToPull;
      this.pullMsg = `Cloud model '${modelToPull}' registered.`;
      this.pullMsgColor = 'text-green-400';
      this.saveConfig();
      return;
    }

    this.socketService.setPulling(modelToPull);
    this.refreshLocalPullState();

    this.orchestratorService.pullOllamaModel(modelToPull).subscribe({
      next: () => {},
      error: (err: any) => {
        this.pullMsgColor = 'text-red-500';
        this.pullMsg = `Error: ${err.error?.detail || err.message}`;
        this.isPulling = false;
        this.socketService.pullState.isPulling = false;
      }
    });
  }

  private refreshLocalPullState() {
    this.isPulling = this.socketService.pullState.isPulling;
    this.pullProgress = this.socketService.pullState.progress;
    this.pullMsg = this.socketService.pullState.message;
    this.pullMsgColor = this.socketService.pullState.statusColor;
  }

  saveConfig() {
    if (this.selectedNode && this.selectedNode.model) {
      this.selectedNode.teamleadModel = this.selectedNode.model;
    }
    this.orchestratorService.saveConfig(this.config).subscribe({
      next: () => {
        this.saveSuccess = true;
        this.refreshSystemStatus();
        setTimeout(() => this.saveSuccess = false, 3000);
      },
      error: (err: any) => {
        console.error('Failed to save config', err);
        alert('Failed to save configuration.');
      }
    });
  }

  ngOnDestroy(): void {
    if (this.statusTimer) {
      clearInterval(this.statusTimer);
    }
    if (this.pullSub) {
      this.pullSub.unsubscribe();
    }
  }
}
