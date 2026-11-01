import { Component, OnInit, OnDestroy, AfterViewInit, ViewChild, ElementRef, ChangeDetectorRef, HostListener } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import { OrchestratorService, AgentLLMConfig, LLMRoutingConfig, LLMPreset, SprintPhase, SprintPhasesResponse } from '../../services/orchestrator.service';

import { SocketService, LiveTestStep } from '../../services/socket.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../core/pipes/translate.pipe';
import { Subscription, forkJoin } from 'rxjs';
import { Office3DScene, Agent3DData, ScreenOverlayPos } from './office-3d.scene';

export interface AgentConfig {
  id: string;
  name: string;
  avatar: string;
  color: string;
  glowColor: string;
  role: string;
  // Coordinates in isometric stage
  x: number;
  y: number;
  deskX: number;
  deskY: number;
  meetingX: number;
  meetingY: number;
  isFlipped: boolean;
  isJumping?: boolean;
  idleState?: 'WANDERING' | 'BREAK' | 'LOUNGE' | 'SERVER' | 'CHAT' | 'ARCADE' | 'WHITEBOARD' | 'LIBRARY' | 'MEETING';
  idleMessage?: string;
  dialoguePartner?: string;
  convPosition?: { x: number; z: number; rotY: number };
}

export interface DialogueScript {
  zone: string;
  topic?: string;
  roles?: string[];
  turns: Array<{ role?: string; text: string }>;
}

export interface RendezvousSpot {
  name: string;
  zone: string;
  idleState: 'BREAK' | 'LOUNGE' | 'SERVER' | 'CHAT' | 'ARCADE' | 'WHITEBOARD' | 'LIBRARY' | 'WANDERING';
  center: { x: number; z: number };
}

@Component({
  selector: 'app-active-projects',
  standalone: true,
  imports: [CommonModule, FormsModule, TranslatePipe],
  templateUrl: './active-projects.component.html',
  styleUrls: ['./active-projects.component.scss']
})
export class ActiveProjectsComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('threeCanvas', { static: false }) canvasRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('threeContainer', { static: false }) containerRef!: ElementRef<HTMLElement>;

  private officeScene: Office3DScene | null = null;
  private overlayReqId: number | null = null;
  public screenOverlays: Map<string, ScreenOverlayPos> = new Map();

  sprints: string[] = [];
  activeSprint: string | null = null;
  phaseTrackerCollapsed: boolean = true;
  missionDropdownOpen: boolean = false;

  sprintPhases: SprintPhasesResponse | null = null;
  selectedPhase: SprintPhase | null = null;
  private phaseSub: Subscription | null = null;

  jobs: any[] = [];
  traces: any[] = [];
  tlSummary: string = "";

  selectedAgent: string | null = null;
  expandedTraces: Set<string> = new Set();

  // 3D Camera Perspective Modes
  cameraMode: 'iso' | 'cinematic' | 'topdown' = 'iso';

  // Live banter ticker
  recentBanter: { speaker: string; text: string; color: string; time: string } | null = null;

  // Realtime Live Test Execution Stream
  liveTestSteps: LiveTestStep[] = [];
  activeTestRunning: boolean = false;

  // Dynamic LLM Routing State
  llmRouting: LLMRoutingConfig | null = null;
  llmPresets: { chat: LLMPreset[]; task: LLMPreset[] } = { chat: [], task: [] };
  currentAgentLLM: AgentLLMConfig = {
    chatProvider: 'ollama',
    chatModel: 'llama3.1:latest',
    taskProvider: 'gemini',
    taskModel: 'gemini-2.0-flash',
    apiKey: '',
    url: ''
  };
  llmSaveSuccess: boolean = false;
  llmSaveMsg: string = '';
  private llmSub: Subscription | null = null;
  private testRunningTimeout: any;

  private sub: Subscription | null = null;
  private sysSub: Subscription | null = null;
  private testSub: Subscription | null = null;
  private movementTimer: any;
  private initTimer: any;
  private dialogueTimers: any[] = [];

  // Floor layout configuration (8 Dedicated Agents)
  agents: AgentConfig[] = [
    { id: 'TeamLead',   name: 'Team Lead',   avatar: 'assets/avatars/teamlead.png',  color: '#facc15', glowColor: 'rgba(250,204,21,0.5)',  role: 'Planlama',   deskX: 750, deskY: 50,  meetingX: 350, meetingY: 250, x: 750, y: 50,  isFlipped: false },
    { id: 'DevOps',     name: 'DevOps',      avatar: 'assets/avatars/devops.png',    color: '#f97316', glowColor: 'rgba(249,115,22,0.5)',  role: 'Altyapı',    deskX: 750, deskY: 150, meetingX: 450, meetingY: 250, x: 750, y: 150, isFlipped: false },
    { id: 'Database',   name: 'Database',    avatar: 'assets/avatars/backend.png',   color: '#14b8a6', glowColor: 'rgba(20,184,166,0.5)',  role: 'Veritabanı', deskX: 860, deskY: 150, meetingX: 400, meetingY: 200, x: 860, y: 150, isFlipped: false },
    { id: 'Frontend',   name: 'Frontend',    avatar: 'assets/avatars/frontend.png',  color: '#06b6d4', glowColor: 'rgba(6,182,212,0.5)',   role: 'UI/UX',      deskX: 750, deskY: 260, meetingX: 520, meetingY: 330, x: 750, y: 260, isFlipped: false },
    { id: 'Backend',    name: 'Backend',     avatar: 'assets/avatars/backend.png',   color: '#10b981', glowColor: 'rgba(16,185,129,0.5)',  role: 'API',        deskX: 750, deskY: 370, meetingX: 450, meetingY: 400, x: 750, y: 370, isFlipped: false },
    { id: 'Security',   name: 'Security',    avatar: 'assets/avatars/security.png',  color: '#ef4444', glowColor: 'rgba(239,68,68,0.5)',   role: 'Güvenlik',   deskX: 750, deskY: 480, meetingX: 350, meetingY: 400, x: 750, y: 480, isFlipped: false },
    { id: 'Tester',     name: 'Tester',      avatar: 'assets/avatars/tester.png',    color: '#a855f7', glowColor: 'rgba(168,85,247,0.5)',  role: 'Test',       deskX: 750, deskY: 580, meetingX: 280, meetingY: 330, x: 750, y: 580, isFlipped: false },
    { id: 'Documenter', name: 'Documenter',  avatar: 'assets/avatars/teamlead.png',  color: '#38bdf8', glowColor: 'rgba(56,189,248,0.5)',  role: 'Döküman',    deskX: 860, deskY: 370, meetingX: 300, meetingY: 250, x: 860, y: 370, isFlipped: false },
  ];

  // Rich Reciprocal Dialogue Library (Turkish Tech Banter & Engineering Humor)
  private readonly dialogueLibrary: DialogueScript[] = [
    // ═══════════════════════════════════════════════════════════════════════════
    // 3-AGENT TRIO CONVERSATIONS (Forming an inward-facing triangle circle)
    // ═══════════════════════════════════════════════════════════════════════════
    {
      zone: 'Whiteboard',
      topic: 'Micro-Frontend & BFF Mimarisi',
      roles: ['TeamLead', 'Backend', 'Frontend'],
      turns: [
        { text: "Yeni mimaride micro-frontend ve BFF (Backend-for-Frontend) desenine geçiyoruz, ne dersiniz?" },
        { text: "BFF harika olur patron! Endpoint'leri tam frontend'in istediği DTO formatında hazırlarım, payload %60 küçülür." },
        { text: "Mükemmel! Ben de UI katmanında component bazlı lazy load kurarım, ilk sayfa yüklemesi 300ms altına iner!" }
      ]
    },
    {
      zone: 'Server Rack',
      topic: 'Zero-Trust Güvenlik & Dayanıklılık',
      roles: ['DevOps', 'Security', 'Database'],
      turns: [
        { text: "Prod Kubernetes kümesine mTLS ve zero-trust service mesh ekledik, pod iletişimi tamamen şifreli." },
        { text: "Statik kod analizi ve sızma testlerini geçirdik, tek bir açık port veya zafiyet kalmadı, süper!" },
        { text: "Veritabanı cluster'ına da failover koruması ve otomatik read replica bağladım, 7/24 kesintisiz ayaktayız!" }
      ]
    },
    {
      zone: 'Water Cooler',
      topic: 'Bug Avı & İdempotency',
      roles: ['Tester', 'Frontend', 'Backend'],
      turns: [
        { text: "Form submit testinde garip bir edge case yakaladım, kullanıcı arka arkaya 5 kez basınca çift kayıt oluşuyor!" },
        { text: "Hemen API'ye idempotency key ve Redis lock mekanizması ekliyorum, aynı istek iki kez işlenemez." },
        { text: "Ben de butona tıklanır tıklanmaz loading spinner ve disable durumu koyuyorum, harika ekip çalışması!" }
      ]
    },
    {
      zone: 'Coffee Stand',
      topic: 'CI/CD Pipeline Hızı',
      roles: ['TeamLead', 'DevOps', 'Tester'],
      turns: [
        { text: "CI/CD pipeline süresi şu an kaç dakikada bitiyor?" },
        { text: "Test paralelleştirme ve Docker layer cache sayesinde 14 dakikadan 2.5 dakikaya indirdik!" },
        { text: "Üstelik tüm end-to-end ve entegrasyon testlerimiz bu 2.5 dakikada eksiksiz koşuyor!" }
      ]
    },
    {
      zone: 'Library',
      topic: 'OpenAPI Kontratları & Tip Güvenliği',
      roles: ['Documenter', 'Backend', 'Frontend'],
      turns: [
        { text: "Tüm endpoint kontratlarını ve OpenAPI spesifikasyonunu tek bir ortak tipler paketine bağladım." },
        { text: "Artık backend DTO değişince TypeScript tipleri otomatik generate edilecek, uyumsuzluk riski sıfır." },
        { text: "Tip güvenliği tam istediğim gibi! Yanlış property yazınca derleyici anında uyaracak, ellerinize sağlık." }
      ]
    },
    {
      zone: 'Coffee Stand',
      topic: 'Kafein & Geliştirici Esprileri',
      roles: ['Backend', 'DevOps', 'Frontend'],
      turns: [
        { text: "3. duble espressoyu aldım, şu an kendimi C++ derleyicisinden daha hızlı hissediyorum!" },
        { text: "Sakin ol şampiyon, geçen sefer öyle dediğinde production sunucusuna drop table atmıştın." },
        { text: "Haha! En azından backup almayı unutmuyoruz, kahveler şirketten bu arada afiyet olsun!" }
      ]
    },
    {
      zone: 'Arcade Machine',
      topic: 'Arcade Bug\'ı & Mesai Eğlencesi',
      roles: ['Tester', 'Security', 'DevOps'],
      turns: [
        { text: "Arcade makinesinin jeton kontrol kodunu test ettim, sınırsız kredi bug'ı var!" },
        { text: "Bunu bir güvenlik açığı olarak değil, mesai sonrası moral optimizasyonu olarak raporluyorum!" },
        { text: "Katılıyorum, bu özelliği prod ortamına bile deploy edebiliriz, kimse görmesin!" }
      ]
    },
    {
      zone: 'Whiteboard',
      topic: 'Büyük Veri & Önbellek Mimarisi',
      roles: ['TeamLead', 'Database', 'Backend'],
      turns: [
        { text: "Milyonluk veri setinde arama sorguları yavaşlamaya başlamıştı, şemayı nasıl bölelim?" },
        { text: "PostgreSQL partitioning ve Elastic arama indeksini ayırdık, sorgu süreleri 15ms'ye geriledi." },
        { text: "Ben de sık okunan verileri Redis'e aldım, cache hit ratio %92'ye çıktı patron!" }
      ]
    },

    // ═══════════════════════════════════════════════════════════════════════════
    // 2-AGENT PAIR CONVERSATIONS (Face-to-Face Looking Directly at Each Other)
    // ═══════════════════════════════════════════════════════════════════════════
    {
      zone: 'Coffee Stand',
      roles: ['Backend', 'DevOps'],
      turns: [
        { text: "3. duble espressoyu aldım, API response süresi 12ms altına indi resmen!" },
        { text: "Kalp ritmine dikkat et usta, prod cluster'ı senden daha sakin çalışıyor." },
        { text: "Redis cache sıcakken kahvem soğuyamaz, mimari felsefem bu!" }
      ]
    },
    {
      zone: 'Coffee Stand',
      roles: ['Frontend', 'TeamLead'],
      turns: [
        { text: "Yeni tasarımda buton bordürlerini 4px yuvarlatıp micro-interaction ekledim." },
        { text: "Kullanıcı deneyimi akıyor! Ama bundle size'ı 200kb altında tutuyoruz değil mi?" },
        { text: "Tree-shaking ve lazy loading devrede patron, kuş gibi hafif!" }
      ]
    },
    {
      zone: 'Coffee Stand',
      roles: ['Tester', 'Security'],
      turns: [
        { text: "Kahve makinesinin para haznesine negatif sayı girdim, bedava mocha verdi!" },
        { text: "Fiziksel bypass zafiyeti! Hemen CVE açıyorum, makineyi karantinaya alın!" },
        { text: "Zafiyet kapatılana kadar kahveler benden o zaman!" }
      ]
    },
    {
      zone: 'Coffee Stand',
      roles: ['Database', 'Backend'],
      turns: [
        { text: "Kahve çekirdekleri bile unindexed tablo gibi dağınık, B-Tree ile sıralayayım dedim." },
        { text: "Aman diyeyim, kahve içerken bari EXPLAIN ANALYZE çalıştırma!" },
        { text: "Alışkanlık işte, index olmayan yerde huzur bulamıyorum." }
      ]
    },
    {
      zone: 'Coffee Stand',
      turns: [
        { text: "Bu kahve makinesinin basınç ayarını kim yaptıysa ellerine sağlık, tam kıvamında." },
        { text: "Kafein olmadan mimari çizilmez zaten, sıradaki faza enerji depoluyoruz!" },
        { text: "Aynen öyle, bir kupa daha alıp kodlara dalalım." }
      ]
    },
    {
      zone: 'Water Cooler',
      roles: ['DevOps', 'Security'],
      turns: [
        { text: "Dün gece firewall loglarında garip bir port taraması gördüm, hemen izole ettim." },
        { text: "Eline sağlık. Zero-trust mimarisi boşuna değil, kimseye şartsız güven yok!" },
        { text: "Aynen öyle, default-deny politikamız tıkır tıkır işliyor." }
      ]
    },
    {
      zone: 'Water Cooler',
      roles: ['Frontend', 'Tester'],
      turns: [
        { text: "CSS flexbox ile dikey ortalama yaparken Chrome ile Safari kavga etti yine." },
        { text: "Test case'e ekledim: 'Kullanıcı garip bir tarayıcı açarsa buton kaçmasın!'" },
        { text: "Hepsinde pixel-perfect oturttum, rahatça test edebilirsin." }
      ]
    },
    {
      zone: 'Water Cooler',
      roles: ['Documenter', 'Backend'],
      turns: [
        { text: "Tüm REST endpoint'leri için OpenAPI 3.1 dokümantasyonunu güncelledin mi?" },
        { text: "Şemalar ve response DTO'ları hazır, swagger arayüzünden test edebilirsin." },
        { text: "Harika, hemen SDK kod üretim aracına bağlıyorum." }
      ]
    },
    {
      zone: 'Water Cooler',
      turns: [
        { text: "Ofisin havası bugün çok dinamik, yeni sprint görevleri tıkır tıkır ilerliyor." },
        { text: "Evet, arka planda çalışan pipeline tam bir saat gibi işliyor." },
        { text: "Ekibin enerjisi harika, teslimatı zamanından önce yaparız!" }
      ]
    },
    {
      zone: 'Server Rack',
      roles: ['DevOps', 'Backend'],
      turns: [
        { text: "Kubernetes pod'ları mis gibi autoscaling yapıyor, CPU kullanımı %18'de stabil." },
        { text: "Asenkron worker kuyruğu mükemmel oturmuş, darboğaz sıfır." },
        { text: "Prod dağıtımı için yeşil ışık yakıyorum o zaman." }
      ]
    },
    {
      zone: 'Server Rack',
      roles: ['DevOps', 'Database'],
      turns: [
        { text: "Master-slave replication gecikmesi 0.02ms. Kusursuz bir senkronizasyon." },
        { text: "Nazar değdirmeyelim, split-brain senaryolarına karşı quorum koruması devrede." },
        { text: "Yedekleme betikleri de her gece saat 03:00'te tetikleniyor." }
      ]
    },
    {
      zone: 'Arcade Machine',
      roles: ['Tester', 'Frontend'],
      turns: [
        { text: "Retro oyunda gizli Easter Egg buldum, duvardan geçince 9999 puan veriyor!" },
        { text: "O bir bug değil, pixel-perfect clipping edge case'i!" },
        { text: "Her halükarda yüksek skor tablosunu ele geçirdim!" }
      ]
    },
    {
      zone: 'Arcade Machine',
      turns: [
        { text: "Bir el dövüş oyunu atalım mı? Kaybeden sıradaki PR'ın review'ını yapar!" },
        { text: "Meydan okumayı kabul ediyorum, kombolarıma güveniyorum!" },
        { text: "Hadi bakalım, klavyeni hazırla!" }
      ]
    },
    {
      zone: 'Whiteboard',
      roles: ['TeamLead', 'Frontend'],
      turns: [
        { text: "Buradaki state management akışında Signals mi yoksa RxJS mi daha efektif?" },
        { text: "Reactivity için Signals harika oldu, boilerplate kod %40 azaldı patron." },
        { text: "Süper, okunabilirlik arttıysa doğru yoldayız." }
      ]
    },
    {
      zone: 'Whiteboard',
      roles: ['TeamLead', 'Database'],
      turns: [
        { text: "Veritabanı şemasında read replica ve cache katmanını buraya konumlandırıyoruz." },
        { text: "Tam isabet. Redis cache TTL'ini 15 dakika yaparsak ana DB nefes alır." },
        { text: "Aynen, veri tabanı CPU'su %30'u geçmeyecek şekilde planlayalım." }
      ]
    },
    {
      zone: 'Library',
      roles: ['Security', 'Documenter'],
      turns: [
        { text: "OWASP Top 10 ve güncel şifreleme standartlarını dökümana işledik mi?" },
        { text: "Hem dokümana hem CI pipeline linter kurallarına bağladım, hepsi hazır!" },
        { text: "Mükemmel uyum, denetimden tam not alacağız." }
      ]
    },
    {
      zone: 'Library',
      turns: [
        { text: "Yazılım mimarisi referans kitaplarına göz atıyordum, temiz kod prensipleri zamansız." },
        { text: "Kesinlikle, sağlam temeller üzerine kurulan kod yıllarca sorunsuz yaşar." },
        { text: "Teknik borcu minimumda tutmanın sırrı bu." }
      ]
    }
  ];

  // Solo greetings and quotes when clicked
  private readonly agentGreetingsTr: Record<string, string> = {
    TeamLead: "Sprint hedeflerimiz net! Ekibin mimari bütünlüğünü ve hızını koordine ediyorum.",
    DevOps: "CI/CD boru hatları ve konteynerler hazır. Dağıtımlar sıfır kesintiyle gerçekleşiyor!",
    Database: "Veritabanı şeması ve indeksler optimize edildi. Veri bütünlüğü en üst düzeyde.",
    Frontend: "Modern, akıcı ve duyarlı arayüz bileşenleri hazır. CSS ve TypeScript tam formunda!",
    Backend: "Yüksek performanslı REST/gRPC endpoint'leri devrede. Hızlı ve dayanıklı API mimarisi.",
    Security: "Sıfır zafiyet politikası devrede. Girdiler doğrulanıyor, siber tehditler engellendi.",
    Tester: "Tüm sınır durumları ve unit testleri hazır. Hiçbir hata gözümüzden kaçamaz!",
    Documenter: "OpenAPI kontratları, Mermaid mimari diyagramları ve rehberler eksiksiz güncel."
  };

  private readonly agentGreetingsEn: Record<string, string> = {
    TeamLead: "Sprint objectives are clear! Coordinating architectural integrity and team velocity.",
    DevOps: "CI/CD pipelines and containers ready. Deployments running with zero downtime!",
    Database: "Database schemas and indices optimized. Data integrity and ACID at peak performance.",
    Frontend: "Modern, responsive UI components styled and loaded. CSS and TypeScript in top shape!",
    Backend: "High-performance REST/gRPC endpoints active. Resilient and fast microservice architecture.",
    Security: "Zero vulnerability policy active. Inputs sanitized, cyber risks neutralized.",
    Tester: "Edge cases and end-to-end tests prepared. Not a single bug escapes verification!",
    Documenter: "OpenAPI contracts, Mermaid architecture diagrams, and dev guides up to date."
  };

  public getAgentGreeting(agentId: string): string {
    const isEn = this.i18n.currentLang === 'en';
    const dict = isEn ? this.agentGreetingsEn : this.agentGreetingsTr;
    return dict[agentId] || (isEn ? "Ready and awaiting mission assignments!" : "Hazırım, görevimi bekliyorum!");
  }

  constructor(
    private orchestratorService: OrchestratorService,
    private socketService: SocketService,
    private cdr: ChangeDetectorRef,
    private route: ActivatedRoute,
    public i18n: I18nService
  ) {}

  ngOnInit(): void {
    this.route.queryParams.subscribe(params => {
      const targetSprint = params['sprint'];
      if (targetSprint && targetSprint.toLowerCase() !== 'idle' && targetSprint !== this.activeSprint) {
        if (!this.sprints.includes(targetSprint)) {
          this.sprints.unshift(targetSprint);
        }
        this.selectSprint(targetSprint);
      }
    });

    this.loadSprints();
    this.loadLLMRouting();
    this.llmSub = this.socketService.llmRoutingUpdate$.subscribe((data: any) => {
      if (data) {
        this.llmRouting = data;
        if (this.selectedAgent) {
          this.syncAgentLLMSettings(this.selectedAgent);
        }
      }
    });

    this.sub = this.socketService.jobUpdate$.subscribe((data: any) => {
      if (data.sprint_id && data.sprint_id.toLowerCase() !== 'idle' && (!this.sprints.includes(data.sprint_id) || data.status === 'STARTED')) {
        this.loadSprints();
      }

      const agentName = data.agent_name || data.agent;
      if (data.status === 'PROCESSING' || data.status === 'WORKING') {
        const workingAgent = this.agents.find(a => a.id === agentName);
        if (workingAgent) {
          workingAgent.convPosition = undefined;
          workingAgent.idleMessage = undefined;
        }
      }

      if (this.activeSprint === data.sprint_id && this.activeSprint !== null) {
        const existingJob = this.jobs.find(j => j.id === data.job_id || (j.agent_name === agentName && j.status === 'PENDING'));

        if (existingJob) {
          existingJob.status = data.status === 'PROCESSING' ? 'WORKING' : data.status;
          if (data.status === 'COMPLETED' || data.status === 'SUCCESS') existingJob.status = 'COMPLETED';
        } else {
          this.jobs.push({
            id: data.job_id,
            agent_name: agentName,
            agent: agentName,
            status: data.status === 'PROCESSING' ? 'WORKING' : data.status,
            sprint_id: data.sprint_id
          });
        }

        this.loadSprintDetail(this.activeSprint);
      }
      this.sync3DScene();
    });

    this.sysSub = this.socketService.systemUpdate$.subscribe((_data: any) => {});

    // Realtime Test Execution Stream
    this.phaseSub = this.socketService.phaseUpdate$.subscribe((data: any) => {
      if (this.activeSprint && data.sprint_id === this.activeSprint) {
        this.loadSprintPhases(this.activeSprint);
        const tl = this.agents.find(a => a.id === 'TeamLead');
        if (tl && data.message) {
          tl.idleMessage = `Faz ${data.phase_number}: ${data.phase_name}`;
          this.recentBanter = {
            speaker: 'TeamLead (Faz Takibi)',
            text: data.message,
            color: '#facc15',
            time: new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          };
          this.sync3DScene();
        }
      }
    });

    this.testSub = this.socketService.liveTestStep$.subscribe((step: LiveTestStep) => {
      this.liveTestSteps.unshift(step);
      if (this.liveTestSteps.length > 30) {
        this.liveTestSteps.pop();
      }
      this.activeTestRunning = true;
      clearTimeout(this.testRunningTimeout);
      this.testRunningTimeout = setTimeout(() => this.activeTestRunning = false, 10000);
      this.sync3DScene();
    });

    // Movement & Interaction Loop: Runs every 6.5 seconds for an alive, dynamic office feel
    this.movementTimer = setInterval(() => this.updateAgentPositions(), 6500);
    // Initial call
    this.initTimer = setTimeout(() => this.updateAgentPositions(), 1200);
  }

  ngAfterViewInit(): void {
    if (this.canvasRef && this.containerRef) {
      this.officeScene = new Office3DScene();
      this.officeScene.init(
        this.canvasRef.nativeElement,
        this.containerRef.nativeElement,
        (agentId: string) => this.selectAgentById(agentId)
      );
      this.sync3DScene();
      this.startOverlayLoop();
    }
  }

  private startOverlayLoop(): void {
    const loop = () => {
      if (this.officeScene) {
        const overlays = this.officeScene.getScreenOverlays();
        overlays.forEach(o => this.screenOverlays.set(o.agentId, o));
        this.cdr.markForCheck();
      }
      this.overlayReqId = requestAnimationFrame(loop);
    };
    this.overlayReqId = requestAnimationFrame(loop);
  }

  public getOverlay(agentId: string): ScreenOverlayPos | undefined {
    return this.screenOverlays.get(agentId);
  }

  public sync3DScene(): void {
    if (!this.officeScene) return;
    const data: Agent3DData[] = this.agents.map(a => ({
      id: a.id,
      name: a.name,
      role: a.role,
      color: a.color,
      glowColor: a.glowColor,
      status: this.getJobStatus(a.id),
      idleState: a.idleState,
      idleMessage: a.idleMessage,
      isJumping: a.isJumping,
      convPosition: a.convPosition
    }));
    this.officeScene.syncAgents(data);
  }

  setCameraMode(mode: 'iso' | 'cinematic' | 'topdown'): void {
    this.cameraMode = mode;
    this.officeScene?.setCameraPreset(mode);
  }

  setCameraPreset(mode: 'iso' | 'cinematic' | 'topdown' | 'warroom' | 'lounge'): void {
    if (mode === 'iso' || mode === 'cinematic' || mode === 'topdown') {
      this.cameraMode = mode;
    }
    this.officeScene?.setCameraPreset(mode);
  }

  resetCamera(): void {
    this.cameraMode = 'iso';
    this.officeScene?.setCameraPreset('iso');
  }

  selectAgentById(agentId: string): void {
    const agent = this.agents.find(a => a.id === agentId);
    if (agent) {
      this.onAgentClick(agent);
    } else {
      this.selectedAgent = agentId;
      this.officeScene?.focusAgent(agentId);
      this.sync3DScene();
    }
  }

  loadSprints(): void {
    this.orchestratorService.getSprints().subscribe({
      next: (res) => {
        // 'idle' aktif bir görev değildir — filtrele
        this.sprints = (res.sprints || []).filter(s => s && s.toLowerCase() !== 'idle').sort().reverse();
        if (this.activeSprint && this.activeSprint.toLowerCase() === 'idle') {
          this.activeSprint = null;
        }
        const targetSprint = this.route.snapshot.queryParams['sprint'];
        if (targetSprint && targetSprint.toLowerCase() !== 'idle') {
          if (!this.sprints.includes(targetSprint)) {
            this.sprints.unshift(targetSprint);
          }
          this.selectSprint(targetSprint);
        } else if (!this.activeSprint && this.sprints.length > 0) {
          this.selectSprint(this.sprints[0]);
        }
      },
      error: (err) => console.error(err)
    });
  }

  togglePhaseTracker(): void {
    this.phaseTrackerCollapsed = !this.phaseTrackerCollapsed;
  }

  getActivePhaseAgents(): string[] {
    if (!this.sprintPhases?.phases) return [];
    const curId = this.sprintPhases.current_phase;
    const curP = this.sprintPhases.phases.find(p => p.phase_id === curId) || this.sprintPhases.phases[0];
    return curP?.participating_agents || (curP?.role ? [curP.role] : []);
  }

  getActivePhaseName(): string {
    if (!this.sprintPhases?.phases) return '';
    const curId = this.sprintPhases.current_phase;
    const curP = this.sprintPhases.phases.find(p => p.phase_id === curId) || this.sprintPhases.phases[0];
    return curP?.name || '';
  }

  toggleMissionDropdown(): void {
    this.missionDropdownOpen = !this.missionDropdownOpen;
  }

  selectSprintFromDropdown(s: string): void {
    this.selectSprint(s);
    this.missionDropdownOpen = false;
  }

  focusAgentFromDrawer(agentId: string): void {
    this.officeScene?.focusAgent(agentId);
  }

  @HostListener('document:click', [''])
  onDocumentClick(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    if (!target.closest('.mission-selector-wrap')) {
      this.missionDropdownOpen = false;
    }
  }

  selectSprint(sprintId: string): void {
    if (!sprintId || sprintId.toLowerCase() === 'idle') {
      this.activeSprint = null;
      this.jobs = [];
      this.traces = [];
      this.sync3DScene();
      return;
    }
    this.activeSprint = sprintId;
    this.selectedAgent = null;
    this.loadSprintDetail(sprintId);
    this.sync3DScene();
  }

  selectDesk(agentId: string): void {
    this.selectedAgent = this.selectedAgent === agentId ? null : agentId;
    if (this.selectedAgent) {
      this.officeScene?.focusAgent(this.selectedAgent);
      this.syncAgentLLMSettings(this.selectedAgent);
    }
    this.sync3DScene();
  }

  closeDetail(): void {
    this.selectedAgent = null;
    this.sync3DScene();
  }

  // Interactive Click: 3D jump hop animation + instant dialogue greeting
  onAgentClick(agent: AgentConfig, event?: MouseEvent): void {
    if (event) {
      event.stopPropagation();
    }
    this.selectDesk(agent.id);
    this.officeScene?.focusAgent(agent.id);

    // 3D Jump trigger
    agent.isJumping = true;
    this.sync3DScene();
    setTimeout(() => {
      agent.isJumping = false;
      this.sync3DScene();
    }, 750);

    const status = this.activeSprint ? this.getJobStatus(agent.id) : 'IDLE';
    if (status !== 'WORKING') {
      const greeting = this.getAgentGreeting(agent.id);
      agent.idleMessage = greeting;
      this.sync3DScene();

      this.recentBanter = {
        speaker: agent.name,
        text: greeting,
        color: agent.color,
        time: new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
      };

      const timer = setTimeout(() => {
        if (agent.idleMessage === greeting) {
          agent.idleMessage = undefined;
          this.sync3DScene();
        }
      }, 5000);
      this.dialogueTimers.push(timer);
    }
  }

  getJobStatus(role: string): string {
    const roleJobs = this.jobs.filter(j => j.agent === role || j.agent_name === role);
    if (roleJobs.length > 0) {
      if (roleJobs.some(j => j.status === 'PROCESSING' || j.status === 'WORKING')) return 'WORKING';
      if (roleJobs.some(j => j.status === 'PENDING')) return 'PENDING';
      if (roleJobs.some(j => j.status === 'FAILED')) return 'FAILED';
      if (roleJobs.every(j => j.status === 'COMPLETED' || j.status === 'SUCCESS')) return 'COMPLETED';
      return roleJobs[0].status;
    }
    if (['Security', 'Tester'].includes(role)) return 'STANDBY';
    if (['Frontend', 'Backend'].includes(role)) return 'AWAITING';
    return 'IDLE';
  }

  getAgentStatusLabel(status: string): string {
    switch (status) {
      case 'WORKING': return '⚡ WORKING...';
      case 'COMPLETED': return '✅ COMPLETED';
      case 'FAILED': return '❌ FAILED';
      case 'PENDING': return '⏳ PENDING';
      case 'STANDBY': return '💤 STANDBY';
      case 'AWAITING': return '📋 AWAITING';
      default: return '○ IDLE';
    }
  }

  activeTab: 'WORK' | 'CHAT' | 'MEMORY' | 'TESTS' | 'LLM' = 'WORK';
  projectMemory: { sprint_id: string; shared_memory: string; agent_memories: Record<string, string> } | null = null;

  get selectedAgentWorkTraces(): any[] {
    if (!this.selectedAgent) return [];
    let list = this.traces.filter(t => (t.agent === this.selectedAgent || t.agent_name === this.selectedAgent) && t.sprint_id !== 'idle');

    const activeJobs = this.jobs.filter(j =>
      (j.status === 'PROCESSING' || j.status === 'WORKING') &&
      (j.agent_name === this.selectedAgent || j.agent === this.selectedAgent)
    );
    const virtualTraces = activeJobs.map(j => ({
      agent: j.agent_name,
      timestamp: j.locked_at || new Date().toISOString(),
      response: `[IN PROGRESS] Working on task:\n${j.prompt || 'Processing...'}`,
      prompt: j.prompt || '',
      isVirtual: true
    }));

    return [...virtualTraces, ...list].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }

  get selectedAgentChatTraces(): any[] {
    if (!this.selectedAgent) return [];
    return this.traces.filter(t => (t.agent === this.selectedAgent || t.agent_name === this.selectedAgent) && t.sprint_id === 'idle')
               .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  }

  getAgentConfig(agentId: string): AgentConfig | undefined {
    return this.agents.find(a => a.id === agentId);
  }

  toggleTrace(timestamp: string): void {
    if (this.expandedTraces.has(timestamp)) {
      this.expandedTraces.delete(timestamp);
    } else {
      this.expandedTraces.add(timestamp);
    }
  }

  isExpanded(timestamp: string): boolean {
    return this.expandedTraces.has(timestamp);
  }

  loadSprintDetail(sid: string): void {
    forkJoin({
      jobsRes: this.orchestratorService.getSprintJobs(sid),
      tracesRes: this.orchestratorService.getSprintTraces(sid)
    }).subscribe({
      next: ({ jobsRes, tracesRes }) => {
        this.jobs = jobsRes.jobs || [];
        this.loadSprintPhases(sid);
        this.loadProjectMemory(sid);
        this.traces = tracesRes.traces || [];

        this.tlSummary = "";
        const tlTrace = this.traces.find(t => (t.agent_name || t.agent) === 'TeamLead');
        if (tlTrace && tlTrace.response) {
          try {
            const match = tlTrace.response.match(/\{[\s\S]*\}/);
            if (match) {
              const plan = JSON.parse(match[0]);
              this.tlSummary = plan.summary_tr || plan.project_name || (Array.isArray(plan.tasks) ? `${plan.tasks.length} tasks planned` : '');
            }
          } catch (e) { }
        }
        this.sync3DScene();
      },
      error: (err) => console.error("Failed to load sprint detail", err)
    });
  }

  // Count completed agents for progress
  get completedCount(): number {
    return this.agents.filter(a => this.getJobStatus(a.id) === 'COMPLETED').length;
  }

  get workingCount(): number {
    return this.agents.filter(a => this.getJobStatus(a.id) === 'WORKING').length;
  }

  get idleCount(): number {
    return this.agents.filter(a => !['WORKING', 'COMPLETED'].includes(this.getJobStatus(a.id))).length;
  }

  // ═══════════════════════════════════════════════════════════════════
  // Dynamic 3D Movement & Reciprocal Conversations Engine
  // ═══════════════════════════════════════════════════════════════════

  // Rendezvous spots with calibrated 3D coordinates in the virtual office
  private readonly rendezvousSpots: RendezvousSpot[] = [
    { name: 'Coffee Stand', zone: 'Coffee Stand', idleState: 'BREAK', center: { x: -9.5, z: -6.5 } },
    { name: 'Water Cooler', zone: 'Water Cooler', idleState: 'CHAT', center: { x: -7.5, z: -7.8 } },
    { name: 'Whiteboard', zone: 'Whiteboard', idleState: 'WHITEBOARD', center: { x: -1.0, z: -8.0 } },
    { name: 'Lounge Plaza', zone: 'Break Room', idleState: 'LOUNGE', center: { x: -8.5, z: -3.5 } },
    { name: 'Arcade Corner', zone: 'Arcade Machine', idleState: 'ARCADE', center: { x: -9.2, z: 0.5 } },
    { name: 'Server Room', zone: 'Server Rack', idleState: 'SERVER', center: { x: -8.5, z: 6.0 } },
    { name: 'Library', zone: 'Library', idleState: 'LIBRARY', center: { x: 3.5, z: -8.0 } },
  ];

  private activeConvInProgress = false;

  // 2 Agent Face-to-Face positioning (1.4m apart, looking directly at each other)
  private positionTwoAgentsFaceToFace(agentA: AgentConfig, agentB: AgentConfig, center: { x: number; z: number }): void {
    const dist = 0.70;
    agentA.convPosition = { x: center.x - dist, z: center.z, rotY: Math.PI / 2 };  // faces +X (towards B)
    agentB.convPosition = { x: center.x + dist, z: center.z, rotY: -Math.PI / 2 }; // faces -X (towards A)
  }

  // 3 Agent Circle formation (R = 0.95m, all facing directly inward to center)
  private positionThreeAgentsCircle(agents: AgentConfig[], center: { x: number; z: number }): void {
    const R = 0.95;
    const angles = [0, (2 * Math.PI) / 3, (4 * Math.PI) / 3];
    agents.forEach((agent, i) => {
      const angle = angles[i % 3];
      const x = center.x + R * Math.cos(angle);
      const z = center.z + R * Math.sin(angle);
      const rotY = Math.atan2(center.x - x, center.z - z);
      agent.convPosition = { x, z, rotY };
    });
  }

  updateAgentPositions(): void {
    const isTeamLeadWorking = this.activeSprint ? this.getJobStatus('TeamLead') === 'WORKING' : false;

    // 1. Position workers at desk or meeting room
    this.agents.forEach(agent => {
      const status = this.activeSprint ? this.getJobStatus(agent.id) : 'IDLE';
      const prevX = agent.x;

      if (isTeamLeadWorking) {
        agent.convPosition = undefined;
        agent.x = agent.meetingX;
        agent.y = agent.meetingY;
        agent.idleState = 'MEETING';
        agent.idleMessage = undefined;
      } else if (status === 'WORKING') {
        agent.convPosition = undefined;
        agent.x = agent.deskX;
        agent.y = agent.deskY;
        agent.idleState = undefined;
        agent.idleMessage = undefined;
        agent.isFlipped = false;
      } else if (!agent.convPosition) {
        // Autonomous agent free roaming & natural office life when not in a conversation group
        if (agent.idleState && agent.idleState !== 'MEETING') {
          const roll = Math.random();
          if (roll < 0.35) {
            agent.idleState = undefined;
            agent.x = agent.deskX;
            agent.y = agent.deskY;
            agent.idleMessage = undefined;
          } else if (roll < 0.75) {
            this.pickRandomOfficeSpot(agent);
          }
        } else {
          if (Math.random() < 0.45) {
            this.pickRandomOfficeSpot(agent);
          }
        }

        agent.isFlipped = agent.x < prevX;
      }
    });

    // 2. Multi-Agent Gathering: Trigger Face-to-Face pairs or Inward Circle trios!
    if (!this.activeConvInProgress && !isTeamLeadWorking) {
      this.triggerMultiAgentGathering();
    }
    this.sync3DScene();
  }

  private pickRandomOfficeSpot(agent: AgentConfig): void {
    const roll = Math.random();
    if (roll < 0.22) {
      agent.idleState = 'BREAK';
      agent.x = 80 + Math.random() * 25;
      agent.y = 80 + Math.random() * 25;
    } else if (roll < 0.40) {
      agent.idleState = 'LOUNGE';
      agent.x = 90 + Math.random() * 25;
      agent.y = 120 + Math.random() * 25;
    } else if (roll < 0.55) {
      agent.idleState = 'ARCADE';
      agent.x = 95 + Math.random() * 20;
      agent.y = 295 + Math.random() * 20;
    } else if (roll < 0.70) {
      agent.idleState = 'CHAT';
      agent.x = 440 + Math.random() * 20;
      agent.y = 95 + Math.random() * 20;
    } else if (roll < 0.82) {
      agent.idleState = 'WHITEBOARD';
      agent.x = 440 + Math.random() * 20;
      agent.y = 495 + Math.random() * 20;
    } else if (roll < 0.90) {
      if (['DevOps', 'Backend', 'Security'].includes(agent.id)) {
        agent.idleState = 'SERVER';
        agent.x = 95 + Math.random() * 15;
        agent.y = 510 + Math.random() * 15;
      } else {
        agent.idleState = 'LIBRARY';
        agent.x = 270 + Math.random() * 20;
        agent.y = 95 + Math.random() * 20;
      }
    } else {
      agent.idleState = 'WANDERING';
      agent.x = 220 + Math.random() * 220;
      agent.y = 350 + Math.random() * 180;
    }
  }

  private triggerMultiAgentGathering(): void {
    if (this.activeConvInProgress) return;

    // Filter available idle agents
    const idleAgents = this.agents.filter(a => {
      const status = this.activeSprint ? this.getJobStatus(a.id) : 'IDLE';
      return status !== 'WORKING' && a.idleState !== 'MEETING';
    });

    if (idleAgents.length < 2) return;

    // When 3 or more agents are available, 50% chance to form a 3-agent circle, otherwise 2-agent pair
    const wantTrio = idleAgents.length >= 3 && Math.random() < 0.50;

    if (wantTrio) {
      // Find a matching trio script from dialogueLibrary or pick 3 idle agents
      const matchingScript = this.dialogueLibrary.find(d =>
        d.roles && d.roles.length === 3 && d.roles.every(r => idleAgents.some(a => a.id === r))
      );

      let trioAgents: AgentConfig[] = [];
      let selectedScript: DialogueScript;

      if (matchingScript && matchingScript.roles) {
        trioAgents = matchingScript.roles.map(r => idleAgents.find(a => a.id === r)!);
        selectedScript = matchingScript;
      } else {
        const shuffled = [...idleAgents].sort(() => 0.5 - Math.random());
        trioAgents = shuffled.slice(0, 3);
        const genericScripts = this.dialogueLibrary.filter(d => d.roles && d.roles.length === 3);
        selectedScript = genericScripts[Math.floor(Math.random() * genericScripts.length)] || {
          zone: 'Whiteboard',
          roles: trioAgents.map(a => a.id),
          turns: [
            { text: "Yeni sprint mimarisini gözden geçiriyordum, tüm modüller hazır mı arkadaşlar?" },
            { text: "Benim tarafımdaki servisler ve konfigürasyonlar tamamlandı, entegrasyonu bekliyorum." },
            { text: "Aynı şekilde! Ekip olarak senkronize çalıştığımızda hiçbir hata karşımızda duramaz." }
          ]
        };
      }

      // Find rendezvous spot
      const spot = this.rendezvousSpots.find(s => s.name === selectedScript.zone || s.zone === selectedScript.zone)
        || this.rendezvousSpots[Math.floor(Math.random() * this.rendezvousSpots.length)];

      // Position in Circle facing inward!
      this.positionThreeAgentsCircle(trioAgents, spot.center);
      trioAgents.forEach(a => a.idleState = spot.idleState);

      // Execute coherent conversation
      this.runCoordinatedConversation(trioAgents, spot, selectedScript);

    } else {
      // 2-Agent Pair (Face-to-Face)
      const matchingScript = this.dialogueLibrary.find(d =>
        d.roles && d.roles.length === 2 && d.roles.every(r => idleAgents.some(a => a.id === r))
      );

      let pairAgents: AgentConfig[] = [];
      let selectedScript: DialogueScript;

      if (matchingScript && matchingScript.roles) {
        pairAgents = matchingScript.roles.map(r => idleAgents.find(a => a.id === r)!);
        selectedScript = matchingScript;
      } else {
        const shuffled = [...idleAgents].sort(() => 0.5 - Math.random());
        pairAgents = shuffled.slice(0, 2);
        const genericScripts = this.dialogueLibrary.filter(d => d.roles && d.roles.length === 2);
        selectedScript = genericScripts[Math.floor(Math.random() * genericScripts.length)] || {
          zone: 'Coffee Stand',
          roles: pairAgents.map(a => a.id),
          turns: [
            { text: "Ofisin havası bugün çok dinamik, yeni geliştirmeler tıkır tıkır ilerliyor." },
            { text: "Evet, arka planda çalışan mimari tam bir saat gibi işliyor." },
            { text: "Kafein de tamamsa teslimata tam gaz hazırız!" }
          ]
        };
      }

      // Find rendezvous spot
      const spot = this.rendezvousSpots.find(s => s.name === selectedScript.zone || s.zone === selectedScript.zone)
        || this.rendezvousSpots[Math.floor(Math.random() * this.rendezvousSpots.length)];

      // Position Face-to-Face!
      this.positionTwoAgentsFaceToFace(pairAgents[0], pairAgents[1], spot.center);
      pairAgents.forEach(a => a.idleState = spot.idleState);

      // Execute coherent conversation
      this.runCoordinatedConversation(pairAgents, spot, selectedScript);
    }
  }

  private runCoordinatedConversation(agents: AgentConfig[], spot: RendezvousSpot, fallbackScript: DialogueScript): void {
    this.activeConvInProgress = true;

    this.dialogueTimers.forEach(t => clearTimeout(t));
    this.dialogueTimers = [];

    const isEn = this.i18n.currentLang === 'en';
    const fallbackTurns = fallbackScript.turns || [];
    const defaultTurn1 = isEn ? "The office vibe today is energetic, all systems ready!" : "Ofisin havası bugün çok dinamik, hazırlıklar tam gaz!";
    const defaultTurn2 = isEn ? "Exactly, we will keep the architecture running like clockwork." : "Aynen öyle, mimariyi tam bir saat gibi işleteceğiz.";
    const defaultTurn3 = isEn ? "Great teamwork! Let us let the code speak for itself." : "Süper uyum! Kodlarımızı konuşturalım o zaman.";

    const speaker1 = agents[0];
    const partner = agents[1];

    // Step 1: First speaker starts dialogue dynamically via LLM (/chat/idle)
    this.orchestratorService.generateIdleChat(speaker1.id, spot.name, partner.id, undefined, this.i18n.currentLang).subscribe({
      next: (res1) => {
        const text1 = (res1 && res1.response) ? res1.response : (fallbackTurns[0]?.text || defaultTurn1);
        this.deliverTurn1(agents, spot, text1, fallbackTurns);
      },
      error: () => {
        const text1 = fallbackTurns[0]?.text || defaultTurn1;
        this.deliverTurn1(agents, spot, text1, fallbackTurns);
      }
    });
  }

  private deliverTurn1(agents: AgentConfig[], spot: RendezvousSpot, text1: string, fallbackTurns: Array<{ text: string }>): void {
    const isEn = this.i18n.currentLang === 'en';
    const defaultTurn2 = isEn ? "Exactly, we will keep the architecture running like clockwork." : "Aynen öyle, mimariyi tam bir saat gibi işleteceğiz.";

    const speaker1 = agents[0];
    speaker1.idleMessage = text1;
    this.recordBanterTrace(speaker1, spot.name, text1);
    this.sync3DScene();

    // Step 2: Second speaker answers dynamically via LLM replying directly to text1!
    const timer2 = setTimeout(() => {
      if (this.activeSprint && this.getJobStatus(agents[1].id) === 'WORKING') {
        this.cleanupConversation(agents);
        return;
      }
      speaker1.idleMessage = undefined;
      const speaker2 = agents[1];

      // LLM call for speaker2 answering speaker1's dynamic words
      this.orchestratorService.generateIdleChat(speaker2.id, spot.name, speaker1.id, text1, this.i18n.currentLang).subscribe({
        next: (res2) => {
          const text2 = (res2 && res2.response) ? res2.response : (fallbackTurns[1]?.text || defaultTurn2);
          this.deliverTurn2(agents, spot, text2, fallbackTurns);
        },
        error: () => {
          const text2 = fallbackTurns[1]?.text || defaultTurn2;
          this.deliverTurn2(agents, spot, text2, fallbackTurns);
        }
      });
    }, 4500);

    this.dialogueTimers.push(timer2);
  }

  private deliverTurn2(agents: AgentConfig[], spot: RendezvousSpot, text2: string, fallbackTurns: Array<{ text: string }>): void {
    const isEn = this.i18n.currentLang === 'en';
    const defaultTurn3 = isEn ? "Great teamwork! Let us let the code speak for itself." : "Süper uyum! Kodlarımızı konuşturalım o zaman.";

    const speaker2 = agents[1];
    speaker2.idleMessage = text2;
    this.recordBanterTrace(speaker2, spot.name, text2);
    this.sync3DScene();

    // Step 3: Third speaker (in 3-agent group) or Speaker 1 concluding (in 2-agent group)
    const timer3 = setTimeout(() => {
      const speaker3 = agents.length > 2 ? agents[2] : agents[0];
      if (this.activeSprint && this.getJobStatus(speaker3.id) === 'WORKING') {
        this.cleanupConversation(agents);
        return;
      }
      speaker2.idleMessage = undefined;

      // LLM call for speaker3 answering speaker2's dynamic words
      this.orchestratorService.generateIdleChat(speaker3.id, spot.name, speaker2.id, text2, this.i18n.currentLang).subscribe({
        next: (res3) => {
          const text3 = (res3 && res3.response) ? res3.response : (fallbackTurns[2]?.text || defaultTurn3);
          this.deliverTurn3(agents, spot, speaker3, text3);
        },
        error: () => {
          const text3 = fallbackTurns[2]?.text || defaultTurn3;
          this.deliverTurn3(agents, spot, speaker3, text3);
        }
      });
    }, 4500);

    this.dialogueTimers.push(timer3);
  }

  private deliverTurn3(agents: AgentConfig[], spot: RendezvousSpot, speaker3: AgentConfig, text3: string): void {
    speaker3.idleMessage = text3;
    this.recordBanterTrace(speaker3, spot.name, text3);
    this.sync3DScene();

    // Clear bubbles after 5.0s
    const timerClear = setTimeout(() => {
      speaker3.idleMessage = undefined;
      this.sync3DScene();

      // Hold the group together for 4.5s more so user sees them together, then release
      const timerRelease = setTimeout(() => {
        this.cleanupConversation(agents);
      }, 4500);
      this.dialogueTimers.push(timerRelease);
    }, 5000);

    this.dialogueTimers.push(timerClear);
  }

  private cleanupConversation(agents: AgentConfig[]): void {
    agents.forEach(a => {
      a.convPosition = undefined;
      a.idleMessage = undefined;
    });
    this.activeConvInProgress = false;
    this.sync3DScene();
  }

  private fetchOrGenerateSoloThought(agent: AgentConfig, zone: string): void {
    // If backend /chat/idle is available, call it; otherwise pick a witty remark
    this.orchestratorService.generateIdleChat(agent.id, zone, undefined, undefined, this.i18n.currentLang).subscribe({
      next: (res) => {
        if (res && res.response) {
          agent.idleMessage = res.response;
          this.recordBanterTrace(agent, zone, res.response);
          this.sync3DScene();

          const clearTimer = setTimeout(() => {
            if (agent.idleMessage === res.response) {
              agent.idleMessage = undefined;
              this.sync3DScene();
            }
          }, 5000);
          this.dialogueTimers.push(clearTimer);
        }
      },
      error: () => {
        // Fallback witty remark
        const fallback = this.getAgentGreeting(agent.id);
        agent.idleMessage = fallback;
        this.recordBanterTrace(agent, zone, fallback);
        this.sync3DScene();

        const clearTimer = setTimeout(() => {
          if (agent.idleMessage === fallback) {
            agent.idleMessage = undefined;
            this.sync3DScene();
          }
        }, 4000);
        this.dialogueTimers.push(clearTimer);
      }
    });
  }

  private recordBanterTrace(agent: AgentConfig, zone: string, text: string): void {
    const timeStr = new Date().toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    this.recentBanter = {
      speaker: agent.name,
      text: text,
      color: agent.color,
      time: timeStr
    };

    this.traces.unshift({
      agent: agent.id,
      agent_name: agent.name,
      timestamp: new Date().toISOString(),
      response: `[${zone}] ${text}`,
      sprint_id: 'idle',
      isVirtual: false
    });
  }

  loadLLMRouting(): void {
    this.orchestratorService.getLLMRouting().subscribe({
      next: (res) => {
        this.llmRouting = res.routing;
        this.llmPresets = res.presets || { chat: [], task: [] };
        if (this.selectedAgent) {
          this.syncAgentLLMSettings(this.selectedAgent);
        }
      },
      error: (err) => console.error('Failed to load LLM routing:', err)
    });
  }

  syncAgentLLMSettings(agentId: string): void {
    if (!this.llmRouting) return;
    const agentOverride = this.llmRouting.agents?.[agentId];
    const defChat = this.llmRouting.defaultChat || { provider: 'ollama', model: 'llama3.1:latest', url: '', apiKey: '' };
    const defTask = this.llmRouting.defaultTask || { provider: 'gemini', model: 'gemini-2.0-flash', url: '', apiKey: '' };

    this.currentAgentLLM = {
      chatProvider: agentOverride?.chatProvider || defChat.provider || 'ollama',
      chatModel: agentOverride?.chatModel || defChat.model || 'llama3.1:latest',
      taskProvider: agentOverride?.taskProvider || defTask.provider || 'gemini',
      taskModel: agentOverride?.taskModel || defTask.model || 'gemini-2.0-flash',
      apiKey: agentOverride?.apiKey || defTask.apiKey || '',
      url: agentOverride?.url || ''
    };
    this.llmSaveSuccess = false;
    this.llmSaveMsg = '';
  }

  setChatProvider(provider: 'ollama' | 'openai' | 'gemini' | 'anthropic'): void {
    this.currentAgentLLM.chatProvider = provider;
    if (provider === 'ollama') this.currentAgentLLM.chatModel = 'llama3.1:latest';
    else if (provider === 'gemini') this.currentAgentLLM.chatModel = 'gemini-2.0-flash';
    else if (provider === 'openai') this.currentAgentLLM.chatModel = 'gpt-4o-mini';
    else if (provider === 'anthropic') this.currentAgentLLM.chatModel = 'claude-3-5-haiku-20241022';
  }

  setTaskProvider(provider: 'ollama' | 'openai' | 'gemini' | 'anthropic'): void {
    this.currentAgentLLM.taskProvider = provider;
    if (provider === 'gemini') this.currentAgentLLM.taskModel = 'gemini-2.0-flash';
    else if (provider === 'openai') this.currentAgentLLM.taskModel = 'gpt-4o';
    else if (provider === 'anthropic') this.currentAgentLLM.taskModel = 'claude-3-5-sonnet-20241022';
    else if (provider === 'ollama') this.currentAgentLLM.taskModel = 'qwen2.5-coder:7b';
  }

  setChatPreset(preset: LLMPreset): void {
    this.currentAgentLLM.chatProvider = preset.provider as any;
    this.currentAgentLLM.chatModel = preset.model;
  }

  setTaskPreset(preset: LLMPreset): void {
    this.currentAgentLLM.taskProvider = preset.provider as any;
    this.currentAgentLLM.taskModel = preset.model;
  }

  saveAgentLLM(applyToAll: boolean = false): void {
    const targetAgent = applyToAll ? 'ALL' : (this.selectedAgent || 'TeamLead');
    this.orchestratorService.saveAgentLLM({
      agent: targetAgent,
      chatProvider: this.currentAgentLLM.chatProvider,
      chatModel: this.currentAgentLLM.chatModel,
      taskProvider: this.currentAgentLLM.taskProvider,
      taskModel: this.currentAgentLLM.taskModel,
      apiKey: this.currentAgentLLM.apiKey,
      url: this.currentAgentLLM.url
    }).subscribe({
      next: (_res) => {
        this.llmSaveSuccess = true;
        this.llmSaveMsg = applyToAll ? '✓ TÜM EKİBİN MODEL AYARLARI GÜNCELLENDİ!' : `✓ ${this.selectedAgent} MODEL AYARLARI KAYDEDİLDİ!`;
        this.loadLLMRouting();
        setTimeout(() => {
          this.llmSaveSuccess = false;
        }, 4000);
      },
      error: (err) => {
        this.llmSaveSuccess = false;
        this.llmSaveMsg = 'Kayıt hatası: ' + (err.error?.detail || err.message);
      }
    });
  }

  resetCurrentAgentToDefaults(): void {
    if (!this.selectedAgent || !this.llmRouting) return;
    const defChat = this.llmRouting.defaultChat || { provider: 'ollama', model: 'llama3.1:latest' };
    const defTask = this.llmRouting.defaultTask || { provider: 'gemini', model: 'gemini-2.0-flash' };
    this.currentAgentLLM.chatProvider = defChat.provider || 'ollama';
    this.currentAgentLLM.chatModel = defChat.model || 'llama3.1:latest';
    this.currentAgentLLM.taskProvider = defTask.provider || 'gemini';
    this.currentAgentLLM.taskModel = defTask.model || 'gemini-2.0-flash';
    this.currentAgentLLM.apiKey = defTask.apiKey || '';
    this.saveAgentLLM(false);
  }

  get globalChatBadge(): string {
    const chat = this.llmRouting?.defaultChat;
    if (!chat) return 'Local Ollama';
    return `${chat.provider.toUpperCase()} (${chat.model})`;
  }

  get globalTaskBadge(): string {
    const task = this.llmRouting?.defaultTask;
    if (!task) return 'Gemini Flash';
    return `${task.provider.toUpperCase()} (${task.model})`;
  }

  getAgentTaskModelBadge(agentId: string): string {
    const override = this.llmRouting?.agents?.[agentId];
    if (override?.taskProvider && override?.taskModel) {
      return `${override.taskProvider.toUpperCase()}: ${override.taskModel}`;
    }
    const defTask = this.llmRouting?.defaultTask;
    if (defTask?.provider && defTask?.model) {
      return `${defTask.provider.toUpperCase()}: ${defTask.model}`;
    }
    return 'Default Task LLM';
  }

  getAgentChatModelBadge(agentId: string): string {
    const override = this.llmRouting?.agents?.[agentId];
    if (override?.chatProvider && override?.chatModel) {
      return `${override.chatProvider.toUpperCase()}: ${override.chatModel}`;
    }
    const defChat = this.llmRouting?.defaultChat;
    if (defChat?.provider && defChat?.model) {
      return `${defChat.provider.toUpperCase()}: ${defChat.model}`;
    }
    return 'Local Ollama';
  }

  loadProjectMemory(sid: string): void {
    this.orchestratorService.getSprintMemory(sid).subscribe({
      next: (data) => this.projectMemory = data,
      error: (err) => console.warn("Could not load sprint memory", err)
    });
  }

  get selectedAgentMemory(): string {
    if (!this.selectedAgent || !this.projectMemory?.agent_memories) return '';
    return this.projectMemory.agent_memories[this.selectedAgent] || '';
  }

  get sharedProjectMemory(): string {
    return this.projectMemory?.shared_memory || '';
  }

  loadSprintPhases(sid: string): void {
    this.orchestratorService.getSprintPhases(sid).subscribe({
      next: (phases) => {
        this.sprintPhases = phases;
        this.sync3DScene();
      },
      error: (err) => console.error("Failed to load sprint phases", err)
    });
  }

  selectPhase(phase: SprintPhase): void {
    this.selectedPhase = this.selectedPhase?.phase_id === phase.phase_id ? null : phase;
    if (this.selectedPhase) {
      this.selectAgentById(phase.role);
    }
  }

  closePhaseDetail(): void {
    this.selectedPhase = null;
  }

  getPhaseStatusLabel(status: string): string {
    const isEn = this.i18n.currentLang === 'en';
    switch (status) {
      case 'IN_PROGRESS': return isEn ? '⚡ WORKING' : '⚡ ÇALIŞIYOR';
      case 'COMPLETED': return isEn ? '✅ COMPLETED' : '✅ TAMAMLANDI';
      case 'FAILED': return isEn ? '❌ REVISION' : '❌ DÜZELTME';
      default: return isEn ? '⏳ PENDING' : '⏳ BEKLİYOR';
    }
  }

  ngOnDestroy(): void {
    if (this.overlayReqId) cancelAnimationFrame(this.overlayReqId);
    this.officeScene?.destroy();
    if (this.sub) this.sub.unsubscribe();
    if (this.sysSub) this.sysSub.unsubscribe();
    if (this.testSub) this.testSub.unsubscribe();
    if (this.llmSub) this.llmSub.unsubscribe();
    if (this.phaseSub) this.phaseSub.unsubscribe();
    if (this.movementTimer) clearInterval(this.movementTimer);
    if (this.initTimer) clearTimeout(this.initTimer);
    if (this.testRunningTimeout) clearTimeout(this.testRunningTimeout);
    this.dialogueTimers.forEach(t => clearTimeout(t));
    this.dialogueTimers = [];
  }
}
