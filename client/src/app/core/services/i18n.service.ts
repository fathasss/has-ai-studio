import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

export type AppLang = 'tr' | 'en';

export interface Translations {
  [key: string]: string | Translations;
}

@Injectable({
  providedIn: 'root'
})
export class I18nService {
  private readonly STORAGE_KEY = 'has_ai_lang';
  private currentLangSubject: BehaviorSubject<AppLang>;
  public lang$: Observable<AppLang>;

  private readonly translations: Record<AppLang, Record<string, string>> = {
    tr: {
      // General & Common
      'common.close': 'Kapat',
      'common.save': 'Kaydet',
      'common.cancel': 'İptal',
      'common.refresh': 'Yenile',
      'common.loading': 'Yükleniyor...',
      'common.status': 'Durum',
      'common.actions': 'İşlemler',
      'common.search': 'Ara...',
      'common.copy': 'Kopyala',
      'common.copied': 'Kopyalandı!',
      'common.yes': 'Evet',
      'common.no': 'Hayır',

      // Navigation
      'nav.brandTitle': 'HAS AI',
      'nav.brandSub': 'Studio',
      'nav.office': 'Office',
      'nav.missionHub': 'Mission Hub',
      'nav.projects': 'Projeler',
      'nav.reports': 'Ekip Raporları',
      'nav.traces': 'Loglar & İzler',
      'nav.errors': 'Hatalar',
      'nav.system': 'Sistem',
      'nav.settings': 'Ayarlar',
      'nav.telemetry': 'Sistem Telemetrisi',
      'nav.network': 'Ağ Trafiği',
      'nav.receive': 'İndirme',
      'nav.transmit': 'Yükleme',

      // Header
      'header.officeTitle': 'AI Development Office',
      'header.missionHubTitle': 'Mission Hub (TeamLead)',
      'header.projectsTitle': 'Proje Arşivi',
      'header.reportsTitle': 'Ekip Raporları',
      'header.tracesTitle': 'Loglar & İzler',
      'header.exceptionsTitle': 'Hata Yönetimi',
      'header.settingsTitle': 'Fabrika Ayarları',
      'header.uptime': 'Uptime',
      'header.tokensMin': 'Tokens/dk',
      'header.collapsePanel': 'Ajan panelini daralt',
      'header.expandPanel': 'Ajan panelini genişlet',
      'header.collapseBtn': 'Paneli Daralt',
      'header.agentsBtn': 'Ajanlar',

      // Right Panel (Agents)
      'agentPanel.title': 'Ajan Dağıtımı',
      'agentPanel.activeCount': 'Aktif',
      'agentPanel.statusWorking': 'ÇALIŞIYOR',
      'agentPanel.statusAvail': 'HAZIR',
      'agentPanel.statusDown': 'KAPALI',

      // Office (3D View & Workspace)
      'office.selectMission': 'Görev Seç:',
      'office.allAgentsFree': 'Tüm Ajanlar Boşta',
      'office.phaseProgress': 'Faz {current} / {total}',
      'office.working': 'Çalışıyor',
      'office.completed': 'Tamamlandı',
      'office.resetCamera': 'Varsayılan Kamera',
      'office.topCamera': 'Kuşbakışı Açı',
      'office.sideCamera': 'İzometrik Açı',
      'office.gridToggle': 'Izgarayı Aç/Kapat',
      'office.cameraControls': 'Kamera Görünümü',
      'office.liveOffice': 'Canlı Geliştirme Ofisi',
      'office.viewMode': '3D Görünüm Modu',
      'office.phasesTracker': 'Faz Takipçisi',
      'office.drawerWork': 'Mevcut İş',
      'office.drawerChat': 'Sohbet',
      'office.drawerMemory': 'Proje Hafızası',
      'office.drawerTests': 'Test Gönder',
      'office.drawerLLM': 'LLM Motoru',
      'office.noActiveJob': 'Bu ajan şu an aktif bir sprint işi yürütmüyor.',
      'office.agentStatus': 'Ajan Durumu',
      'office.currentTask': 'Mevcut Görev',
      'office.targetFile': 'Hedef Dosya',
      'office.fileAction': 'Dosya İşlemi',
      'office.priority': 'Öncelik',
      'office.livePrompt': 'Canlı Prompt',
      'office.liveResponse': 'Canlı Yanıt',
      'office.sharedProjectMemory': 'Paylaşılan Proje Hafızası',
      'office.agentSpecificMemory': 'Ajana Özel Hafıza',
      'office.noSharedMemory': 'Henüz bu proje için paylaşılan mimari hafıza oluşmadı.',
      'office.noAgentMemory': 'Henüz bu ajan için özel hafıza kaydı bulunmuyor.',
      'office.testPromptPlaceholder': 'Ajana doğrudan bir test komutu veya prompt gönderin...',
      'office.sendTestJob': '⚡ Test İşini LLM Kuyruğuna Gönder',
      'office.dualEngineTitle': 'Çift Motorlu Hibrit LLM Yapılandırması',
      'office.chatEngine': 'Ofis İçi Serbest Sohbet & Idle LLM',
      'office.taskEngine': 'Resmi Sprint Görevleri & Kod Üretimi LLM',
      'office.provider': 'Sağlayıcı (Provider)',
      'office.model': 'Model Adı',
      'office.apiKey': 'API Anahtarı',
      'office.apiUrl': 'Özel Endpoint URL',
      'office.saveAgentConfig': 'Ajan Motor Ayarlarını Kaydet',
      'office.configSavedSuccess': 'Ajan motor yapılandırması başarıyla kaydedildi!',
      'office.clearAgentFilter': 'Filtreyi Temizle',
      'office.clickAgentToInspect': 'İncelemek için ofisteki bir ajana veya listeye tıklayın.',
      'office.participatingAgents': 'Görevli Ajanlar:',
      'office.deliverables': 'Çıktılar & Teslimatlar:',

      // Mission Hub (TeamLead Dashboard)
      'missionHub.projectHistory': 'Proje Geçmişi',
      'missionHub.projectsCount': 'Proje',
      'missionHub.noProjects': 'Henüz kayıtlı proje oturumu yok.',
      'missionHub.startNewProject': '+ Yeni Proje Başlat',
      'missionHub.architectureStation': 'TeamLead Mimari Çözüm İstasyonu',
      'missionHub.projectLabel': 'Proje:',
      'missionHub.waitingLabel': 'Bekleniyor...',
      'missionHub.roleTeamLead': '👑 TeamLead (Mimar)',
      'missionHub.rolePO': '👤 Ürün Sahibi (PO)',
      'missionHub.teamLeadThinking': 'TeamLead düşünüyor...',
      'missionHub.planReadyTitle': 'Mimari Plan Hazır — Onay Bekleniyor',
      'missionHub.planReadyDesc': 'Projeyi onayladığınızda ekibimiz ihtiyaçlara göre belirlenen dinamik fazlarda geliştirmeye başlayacaktır:',
      'missionHub.phase1Title': 'Faz 1: Altyapı & Veri Mimarisi',
      'missionHub.phase2Title': 'Faz 2: İş Mantığı & Web UI',
      'missionHub.phase3Title': 'Faz 3: Güvenlik, Test & Teslimat',
      'missionHub.approveAndStart': '⚡ PROJEYİ ONAYLA VE GELİŞTİRMEYİ BAŞLAT',
      'missionHub.previewPlanBtn': '🔍 Plan & Görev Detaylarını İncele',
      'missionHub.strategyUpdating': 'Strateji Güncelleniyor...',
      'missionHub.strategyReady': 'Geliştirme Planı Onaya Hazır',
      'missionHub.strategyUpdatingDesc': 'TeamLead en son girdiğinize göre mimariyi güncelliyor...',
      'missionHub.strategyReadyDesc': 'Ayrıntılı proje mimarisi ve görev şeması hazırlandı. İncelemek için tıklayın.',
      'missionHub.reviewPlan': 'Planı İncele',
      'missionHub.approveAndStartShort': 'ONAYLA & BAŞLAT',
      'missionHub.inputPlaceholder': 'TeamLead ile konuşun veya yeni bir yazılım projesi tarif edin...',
      'missionHub.send': 'Gönder',
      'missionHub.previewModalTitle': 'Mimari Geliştirme Planı Önizleme',
      'missionHub.planLoading': 'Mimari plan yapısı hazırlanıyor... Lütfen bekleyin...',
      'missionHub.planError': 'Plan ayrıştırılamadı:',
      'missionHub.orchestrationGuidance': 'Orkestrasyon & Mimari Rehberlik',
      'missionHub.coreStrategy': 'Temel Geliştirme Stratejisi',
      'missionHub.executionPipeline': 'İcra Hattı (Ajan Görevleri)',
      'missionHub.planPreparing': 'Plan hazırlanıyor...',
      'missionHub.planApprovalStarting': 'Onaylandı, başlatılıyor...',
      'missionHub.planApprovalError': 'Başlatma hatası oluştu',
      'missionHub.initialTeamLeadMessage': 'TeamLead devrede. Mimari orkestrasyon hattı hazır ve dinlemede.\n\nYeni proje gereksinimlerinizi bekliyorum, PO.',

      // Project Archive
      'projects.title': 'Proje Arşivi & Dosya Gezgini',
      'projects.subtitle': 'Ajanların ürettiği kaynak kodları ve proje dosyalarını canlı inceleyin.',
      'projects.selectProject': 'Proje Seçiniz',
      'projects.selectProjectPlaceholder': 'İncelemek istediğiniz projeyi seçin...',
      'projects.fileTree': 'Dosya Ağacı',
      'projects.fileViewer': 'Dosya Görüntüleyici',
      'projects.noProjectSelected': 'Lütfen incelemek için yukarıdan bir proje seçin.',
      'projects.noFiles': 'Bu projede henüz dosya bulunmuyor.',
      'projects.downloadFile': 'Dosyayı İndir',
      'projects.lines': 'Satır',
      'projects.bytes': 'Bayt',

      // Team Reports
      'reports.title': 'Ekip Sprint Raporları',
      'reports.subtitle': 'Her sprint ve faz sonunda ajanlar tarafından otomatik üretilen dokümantasyon ve metrikler.',
      'reports.selectSession': 'Sprint Oturumu Seç:',
      'reports.sessionFiles': 'Oturum Rapor Dosyaları',
      'reports.reportPreview': 'Rapor İçeriği',
      'reports.noReports': 'Henüz kayıtlı bir rapor bulunmamaktadır.',
      'reports.selectReportToRead': 'Okumak için sol taraftan bir rapor dosyası seçin.',

      // Logs & Traces
      'traces.title': 'LLM Yürütme Logları & Telemetri',
      'traces.subtitle': 'Her ajanın Ollama veya harici sağlayıcılar üzerindeki prompt/yanıt izleri ve gecikme analizleri.',
      'traces.filterAgent': 'Ajana Göre Filtrele:',
      'traces.allAgents': 'Tüm Ajanlar',
      'traces.filterStatus': 'Durum:',
      'traces.allStatuses': 'Tüm Durumlar',
      'traces.statusSuccess': 'BAŞARILI',
      'traces.statusError': 'HATA',
      'traces.tableTime': 'Zaman',
      'traces.tableAgent': 'Ajan',
      'traces.tableJob': 'İş / Görev',
      'traces.tableLatency': 'Gecikme (ms)',
      'traces.tableTokens': 'Token (P / C / Toplam)',
      'traces.tableStatus': 'Durum',
      'traces.tableDetails': 'Detay',
      'traces.promptView': 'Prompt İçeriği',
      'traces.responseView': 'Model Yanıtı',
      'traces.noTraces': 'Henüz kaydedilmiş bir LLM izi bulunmuyor.',

      // Exceptions
      'exceptions.title': 'Sistem Hata & İstisna Takipçisi',
      'exceptions.subtitle': 'Çalışma zamanında meydana gelen pipeline, LLM ve ajan hatalarının denetim günlüğü.',
      'exceptions.resolved': 'Çözüldü',
      'exceptions.unresolved': 'Aktif Hata',
      'exceptions.noExceptions': 'Harika! Sistemde kayıtlı herhangi bir hata veya istisna bulunmuyor.',
      'exceptions.markResolved': 'Çözüldü Olarak İşaretle',

      // Settings
      'settings.title': 'Fabrika Yapılandırması & LLM Yönlendirme',
      'settings.subtitle': 'Ollama yerel modelleri ve harici API sağlayıcıları (OpenAI, Gemini, Anthropic) için küresel ayarlar.',
      'settings.defaultRouting': 'Genel Varsayılan Yönlendirme',
      'settings.defaultChatModel': 'Varsayılan Sohbet / Idle Modeli',
      'settings.defaultTaskModel': 'Varsayılan Görev / Kod Modeli',
      'settings.agentOverrides': 'Ajana Özel Motor Tanımlamaları',
      'settings.saveSuccess': 'Ayarlar başarıyla kaydedildi!',
      'settings.pullModel': 'Model İndir (Ollama Pull)',
      'settings.modelPullPlaceholder': 'Örn: qwen2.5-coder:7b',
      'settings.pullBtn': 'İndir',
      'settings.pulling': 'İndiriliyor...',
    },
    en: {
      // General & Common
      'common.close': 'Close',
      'common.save': 'Save',
      'common.cancel': 'Cancel',
      'common.refresh': 'Refresh',
      'common.loading': 'Loading...',
      'common.status': 'Status',
      'common.actions': 'Actions',
      'common.search': 'Search...',
      'common.copy': 'Copy',
      'common.copied': 'Copied!',
      'common.yes': 'Yes',
      'common.no': 'No',

      // Navigation
      'nav.brandTitle': 'HAS AI',
      'nav.brandSub': 'Studio',
      'nav.office': 'Office',
      'nav.missionHub': 'Mission Hub',
      'nav.projects': 'Projects',
      'nav.reports': 'Team Reports',
      'nav.traces': 'Logs & Traces',
      'nav.errors': 'Errors',
      'nav.system': 'System',
      'nav.settings': 'Settings',
      'nav.telemetry': 'System Telemetry',
      'nav.network': 'Network Traffic',
      'nav.receive': 'Receive',
      'nav.transmit': 'Transmit',

      // Header
      'header.officeTitle': 'AI Development Office',
      'header.missionHubTitle': 'Mission Hub (TeamLead)',
      'header.projectsTitle': 'Project Archive',
      'header.reportsTitle': 'Team Reports',
      'header.tracesTitle': 'Logs & Traces',
      'header.exceptionsTitle': 'Exception Handling',
      'header.settingsTitle': 'Factory Settings',
      'header.uptime': 'Uptime',
      'header.tokensMin': 'Tokens/m',
      'header.collapsePanel': 'Collapse agent panel',
      'header.expandPanel': 'Expand agent panel',
      'header.collapseBtn': 'Collapse Panel',
      'header.agentsBtn': 'Agents',

      // Right Panel (Agents)
      'agentPanel.title': 'Agent Deployment',
      'agentPanel.activeCount': 'Active',
      'agentPanel.statusWorking': 'WORKING',
      'agentPanel.statusAvail': 'AVAIL',
      'agentPanel.statusDown': 'DOWN',

      // Office (3D View & Workspace)
      'office.selectMission': 'Select Mission:',
      'office.allAgentsFree': 'All Agents Free',
      'office.phaseProgress': 'Phase {current} / {total}',
      'office.working': 'Working',
      'office.completed': 'Completed',
      'office.resetCamera': 'Default Camera',
      'office.topCamera': 'Top View',
      'office.sideCamera': 'Isometric View',
      'office.gridToggle': 'Toggle Grid',
      'office.cameraControls': 'Camera View',
      'office.liveOffice': 'Live Development Office',
      'office.viewMode': '3D View Mode',
      'office.phasesTracker': 'Phase Tracker',
      'office.drawerWork': 'Current Work',
      'office.drawerChat': 'Chat',
      'office.drawerMemory': 'Project Memory',
      'office.drawerTests': 'Send Tests',
      'office.drawerLLM': 'LLM Engine',
      'office.noActiveJob': 'This agent is not executing an active sprint job right now.',
      'office.agentStatus': 'Agent Status',
      'office.currentTask': 'Current Task',
      'office.targetFile': 'Target File',
      'office.fileAction': 'File Action',
      'office.priority': 'Priority',
      'office.livePrompt': 'Live Prompt',
      'office.liveResponse': 'Live Response',
      'office.sharedProjectMemory': 'Shared Project Memory',
      'office.agentSpecificMemory': 'Agent-Specific Memory',
      'office.noSharedMemory': 'No shared architectural memory recorded for this project yet.',
      'office.noAgentMemory': 'No specific memory logs found for this agent yet.',
      'office.testPromptPlaceholder': 'Send a direct test command or prompt to this agent...',
      'office.sendTestJob': '⚡ Send Test Job to LLM Queue',
      'office.dualEngineTitle': 'Dual-Engine Hybrid LLM Architecture',
      'office.chatEngine': 'Free Office Chat & Idle Banter LLM',
      'office.taskEngine': 'Official Sprint Tasks & Code Generation LLM',
      'office.provider': 'Provider',
      'office.model': 'Model Name',
      'office.apiKey': 'API Key',
      'office.apiUrl': 'Custom Endpoint URL',
      'office.saveAgentConfig': 'Save Agent Engine Settings',
      'office.configSavedSuccess': 'Agent engine settings successfully saved!',
      'office.clearAgentFilter': 'Clear Filter',
      'office.clickAgentToInspect': 'Click an agent in the 3D office or list to inspect details.',
      'office.participatingAgents': 'Assigned Agents:',
      'office.deliverables': 'Outputs & Deliverables:',

      // Mission Hub (TeamLead Dashboard)
      'missionHub.projectHistory': 'Project History',
      'missionHub.projectsCount': 'Projects',
      'missionHub.noProjects': 'No recorded project sessions yet.',
      'missionHub.startNewProject': '+ Start New Project',
      'missionHub.architectureStation': 'TeamLead Architecture Solution Station',
      'missionHub.projectLabel': 'Project:',
      'missionHub.waitingLabel': 'Awaiting...',
      'missionHub.roleTeamLead': '👑 TeamLead (Architect)',
      'missionHub.rolePO': '👤 Product Owner (PO)',
      'missionHub.teamLeadThinking': 'TeamLead is thinking...',
      'missionHub.planReadyTitle': 'Architecture Plan Ready — Awaiting Approval',
      'missionHub.planReadyDesc': 'Upon approval, our team will commence development across dynamic milestone phases tailored to requirements:',
      'missionHub.phase1Title': 'Phase 1: Infrastructure & Data Architecture',
      'missionHub.phase2Title': 'Phase 2: Business Logic & Web UI',
      'missionHub.phase3Title': 'Phase 3: Security, Testing & Delivery',
      'missionHub.approveAndStart': '⚡ APPROVE PROJECT & LAUNCH DEVELOPMENT',
      'missionHub.previewPlanBtn': '🔍 Inspect Plan & Task Breakdown',
      'missionHub.strategyUpdating': 'Updating Strategy...',
      'missionHub.strategyReady': 'Development Plan Ready for Approval',
      'missionHub.strategyUpdatingDesc': 'TeamLead is revising architecture based on your latest input...',
      'missionHub.strategyReadyDesc': 'Detailed project architecture and task matrix prepared. Click to inspect.',
      'missionHub.reviewPlan': 'Review Plan',
      'missionHub.approveAndStartShort': 'APPROVE & START',
      'missionHub.inputPlaceholder': 'Chat with TeamLead or describe a new software project...',
      'missionHub.send': 'Send',
      'missionHub.previewModalTitle': 'Architectural Plan Preview',
      'missionHub.planLoading': 'Preparing architecture plan... Please wait...',
      'missionHub.planError': 'Unable to parse plan:',
      'missionHub.orchestrationGuidance': 'Orchestration & Architectural Guidance',
      'missionHub.coreStrategy': 'Core Development Strategy',
      'missionHub.executionPipeline': 'Execution Pipeline (Agent Task Matrix)',
      'missionHub.planPreparing': 'Preparing plan...',
      'missionHub.planApprovalStarting': 'Approved, starting...',
      'missionHub.planApprovalError': 'Execution launch error occurred',
      'missionHub.initialTeamLeadMessage': 'TeamLead active. Architectural orchestration pipeline is ready and listening.\n\nAwaiting your project requirements, PO.',

      // Project Archive
      'projects.title': 'Project Archive & File Explorer',
      'projects.subtitle': 'Inspect codebases and artifacts produced live by AI agents.',
      'projects.selectProject': 'Select Project',
      'projects.selectProjectPlaceholder': 'Choose a project to inspect...',
      'projects.fileTree': 'File Tree',
      'projects.fileViewer': 'File Viewer',
      'projects.noProjectSelected': 'Please select a project from above to inspect.',
      'projects.noFiles': 'No files found in this project repository yet.',
      'projects.downloadFile': 'Download File',
      'projects.lines': 'Lines',
      'projects.bytes': 'Bytes',

      // Team Reports
      'reports.title': 'Team Sprint Reports',
      'reports.subtitle': 'Documentation, test summaries, and metrics generated automatically at phase completion.',
      'reports.selectSession': 'Select Sprint Session:',
      'reports.sessionFiles': 'Session Report Files',
      'reports.reportPreview': 'Report Content',
      'reports.noReports': 'No reports recorded yet.',
      'reports.selectReportToRead': 'Select a report file from the left to read.',

      // Logs & Traces
      'traces.title': 'LLM Execution Traces & Telemetry',
      'traces.subtitle': 'Real-time prompt/response traces, token metrics, and latency diagnostics across models.',
      'traces.filterAgent': 'Filter by Agent:',
      'traces.allAgents': 'All Agents',
      'traces.filterStatus': 'Status:',
      'traces.allStatuses': 'All Statuses',
      'traces.statusSuccess': 'SUCCESS',
      'traces.statusError': 'ERROR',
      'traces.tableTime': 'Timestamp',
      'traces.tableAgent': 'Agent',
      'traces.tableJob': 'Job / Task',
      'traces.tableLatency': 'Latency (ms)',
      'traces.tableTokens': 'Tokens (P / C / Total)',
      'traces.tableStatus': 'Status',
      'traces.tableDetails': 'Details',
      'traces.promptView': 'Prompt Content',
      'traces.responseView': 'Model Response',
      'traces.noTraces': 'No LLM traces recorded yet.',

      // Exceptions
      'exceptions.title': 'System Exception & Error Tracker',
      'exceptions.subtitle': 'Runtime audit trail of pipeline, orchestration, and agent failures.',
      'exceptions.resolved': 'Resolved',
      'exceptions.unresolved': 'Active Error',
      'exceptions.noExceptions': 'Awesome! No active runtime errors or exceptions found.',
      'exceptions.markResolved': 'Mark as Resolved',

      // Settings
      'settings.title': 'Factory Configuration & LLM Routing',
      'settings.subtitle': 'Global routing and per-agent configuration for Ollama and external API providers.',
      'settings.defaultRouting': 'Global Default Routing',
      'settings.defaultChatModel': 'Default Chat / Idle Model',
      'settings.defaultTaskModel': 'Default Task / Code Model',
      'settings.agentOverrides': 'Per-Agent Model Overrides',
      'settings.saveSuccess': 'Settings successfully saved!',
      'settings.pullModel': 'Pull Ollama Model',
      'settings.modelPullPlaceholder': 'e.g. qwen2.5-coder:7b',
      'settings.pullBtn': 'Pull',
      'settings.pulling': 'Pulling...',
    }
  };

  constructor() {
    const saved = (typeof window !== 'undefined' && window.localStorage)
      ? (localStorage.getItem(this.STORAGE_KEY) as AppLang)
      : null;
    const initialLang: AppLang = (saved === 'en' || saved === 'tr') ? saved : 'tr';
    this.currentLangSubject = new BehaviorSubject<AppLang>(initialLang);
    this.lang$ = this.currentLangSubject.asObservable();
  }

  public get currentLang(): AppLang {
    return this.currentLangSubject.value;
  }

  public setLanguage(lang: AppLang): void {
    if (lang !== this.currentLangSubject.value) {
      if (typeof window !== 'undefined' && window.localStorage) {
        localStorage.setItem(this.STORAGE_KEY, lang);
      }
      this.currentLangSubject.next(lang);
    }
  }

  public t(key: string, params?: Record<string, string | number>): string {
    const lang = this.currentLang;
    let translation = this.translations[lang]?.[key] || this.translations['tr']?.[key] || key;

    if (params) {
      for (const [k, v] of Object.entries(params)) {
        translation = translation.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
      }
    }
    return translation;
  }
}

