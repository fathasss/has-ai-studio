import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

export interface Agent3DData {
  id: string;
  name: string;
  role: string;
  color: string;
  glowColor: string;
  status: string; // 'WORKING' | 'COMPLETED' | 'IDLE' | 'FAILED' | 'PENDING'
  idleState?: string;
  idleMessage?: string;
  isJumping?: boolean;
  convPosition?: { x: number; z: number; rotY: number };
}

export interface ScreenOverlayPos {
  agentId: string;
  x: number;
  y: number;
  visible: boolean;
}

export class Office3DScene {
  private canvas!: HTMLCanvasElement;
  private container!: HTMLElement;
  private scene!: THREE.Scene;
  private camera!: THREE.PerspectiveCamera;
  private renderer!: THREE.WebGLRenderer;
  private controls!: OrbitControls;

  private reqId: number | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private raycaster = new THREE.Raycaster();
  private mouse = new THREE.Vector2();

  private agentMeshes = new Map<string, THREE.Group>();
  private deskMeshes = new Map<string, THREE.Group>();
  private animatedProps: Array<{ mesh: THREE.Object3D; update: (t: number) => void }> = [];

  private selectedAgentId: string | null = null;
  private onAgentClickCb?: (agentId: string) => void;

  // Camera animation
  private isCameraTransitioning = false;
  private camStartPos = new THREE.Vector3();
  private camEndPos = new THREE.Vector3();
  private targetStartPos = new THREE.Vector3();
  private targetEndPos = new THREE.Vector3();
  private camTransitionProgress = 1;
  private camTransitionSpeed = 2.5;
  private lastFrameTime = 0;

  // 3D coordinates for zones in the office with orientation and seating
  private readonly zoneCoords: Record<string, { pos: THREE.Vector3; rotY: number; isSeated?: boolean }> = {
    'BREAK':          { pos: new THREE.Vector3(-10.5, 0, -6.8), rotY: Math.PI / 2 },
    'Coffee Stand':   { pos: new THREE.Vector3(-10.5, 0, -6.8), rotY: Math.PI / 2 },
    'Break Room':     { pos: new THREE.Vector3(-10.5, 0, -6.8), rotY: Math.PI / 2 },
    'LOUNGE':         { pos: new THREE.Vector3(-10.7, 0, -5.0), rotY: 0, isSeated: true }, // Seated on couch!
    'Lounge':         { pos: new THREE.Vector3(-10.7, 0, -5.0), rotY: 0, isSeated: true },
    'SOFA':           { pos: new THREE.Vector3(-10.7, 0, -5.0), rotY: 0, isSeated: true },
    'CHAT':           { pos: new THREE.Vector3(-8.1, 0, -8.3), rotY: -Math.PI / 4 },
    'Water Cooler':   { pos: new THREE.Vector3(-8.1, 0, -8.3), rotY: -Math.PI / 4 },
    'SERVER':         { pos: new THREE.Vector3(-10.5, 0, 6.5), rotY: -Math.PI / 2 },
    'Server Rack':    { pos: new THREE.Vector3(-10.5, 0, 6.5), rotY: -Math.PI / 2 },
    'ARCADE':         { pos: new THREE.Vector3(-10.5, 0, 0.5), rotY: -Math.PI / 2 },
    'Arcade Machine': { pos: new THREE.Vector3(-10.5, 0, 0.5), rotY: -Math.PI / 2 },
    'WHITEBOARD':     { pos: new THREE.Vector3(-1.0, 0, -9.5), rotY: -Math.PI },
    'Whiteboard':     { pos: new THREE.Vector3(-1.0, 0, -9.5), rotY: -Math.PI },
    'LIBRARY':        { pos: new THREE.Vector3(4.5, 0, -9.5), rotY: -Math.PI },
    'Library':        { pos: new THREE.Vector3(4.5, 0, -9.5), rotY: -Math.PI },
    'WARROOM':        { pos: new THREE.Vector3(0, 0, 0), rotY: 0 },
    'War Room':       { pos: new THREE.Vector3(0, 0, 0), rotY: 0 },
    'MEETING':        { pos: new THREE.Vector3(0, 0, 0), rotY: 0, isSeated: true },
    'Meeting Room':   { pos: new THREE.Vector3(0, 0, 0), rotY: 0, isSeated: true }
  };

  private readonly wanderWaypoints: THREE.Vector3[] = [
    new THREE.Vector3(0, 0, 4.5),     // Center front hallway
    new THREE.Vector3(-3.5, 0, 2.5),  // Between war room and arcade
    new THREE.Vector3(3.5, 0, 2.5),   // Between war room and workstations
    new THREE.Vector3(-3.5, 0, -3.5), // Hallway near lounge
    new THREE.Vector3(2.5, 0, -6.5),  // Corridor near library
    new THREE.Vector3(-6.5, 0, 0),    // West corridor
    new THREE.Vector3(0, 0, -5.5),    // Behind war room
    new THREE.Vector3(4.5, 0, 6.5)    // Near tester pod aisle
  ];

  // 8 Dedicated Developer Pods (Desks)
  private readonly deskPositions: Record<string, { x: number; z: number; rotY: number }> = {
    TeamLead:   { x: 7,   z: -6.5, rotY: -Math.PI / 2 },
    DevOps:     { x: 12,  z: -6.5, rotY: -Math.PI / 2 },
    Database:   { x: 7,   z: -2.2, rotY: -Math.PI / 2 },
    Frontend:   { x: 12,  z: -2.2, rotY: -Math.PI / 2 },
    Backend:    { x: 7,   z: 2.2,  rotY: -Math.PI / 2 },
    Security:   { x: 12,  z: 2.2,  rotY: -Math.PI / 2 },
    Tester:     { x: 7,   z: 6.5,  rotY: -Math.PI / 2 },
    Documenter: { x: 12,  z: 6.5,  rotY: -Math.PI / 2 }
  };

  // Meeting Table seat offsets around conference table (circle radius 3.1)
  private readonly meetingSeats: Record<string, THREE.Vector3> = {
    TeamLead:   new THREE.Vector3(0, 0, -3.1),
    DevOps:     new THREE.Vector3(2.19, 0, -2.19),
    Database:   new THREE.Vector3(3.1, 0, 0),
    Frontend:   new THREE.Vector3(2.19, 0, 2.19),
    Backend:    new THREE.Vector3(0, 0, 3.1),
    Security:   new THREE.Vector3(-2.19, 0, 2.19),
    Tester:     new THREE.Vector3(-3.1, 0, 0),
    Documenter: new THREE.Vector3(-2.19, 0, -2.19)
  };

  constructor() {}

  init(
    canvas: HTMLCanvasElement,
    container: HTMLElement,
    onAgentClick: (agentId: string) => void
  ): void {
    this.canvas = canvas;
    this.container = container;
    this.onAgentClickCb = onAgentClick;

    const width = container.clientWidth || 960;
    const height = container.clientHeight || 650;

    // 1. Scene
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0a0e17);
    this.scene.fog = new THREE.FogExp2(0x0a0e17, 0.012);

    // 2. Camera
    this.camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 200);
    this.camera.position.set(22, 19, 22);

    // 3. Renderer
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      powerPreference: 'high-performance'
    });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;

    // 4. Controls
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.maxPolarAngle = Math.PI / 2.08; // don't go below ground
    this.controls.minDistance = 6;
    this.controls.maxDistance = 55;
    this.controls.target.set(1.5, 0, 0);

    // 5. Lighting
    this.setupLights();

    // 6. Office Architecture & Zones
    this.buildOfficeEnvironment();

    // 7. Event Listeners
    this.canvas.addEventListener('click', (e) => this.onPointerClick(e));
    this.canvas.addEventListener('mousemove', (e) => this.onPointerMove(e));

    this.resizeObserver = new ResizeObserver(() => this.onResize());
    this.resizeObserver.observe(this.container);

    // 8. Start Loop
    this.animate(0);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // LIGHTING
  // ═══════════════════════════════════════════════════════════════════════════
  private setupLights(): void {
    // Ambient light: soft cool office glow
    const ambientLight = new THREE.AmbientLight(0xdce7fe, 0.85);
    this.scene.add(ambientLight);

    // Main directional sun / ceiling key light with soft shadow
    const dirLight = new THREE.DirectionalLight(0xfff5ea, 1.4);
    dirLight.position.set(18, 28, 16);
    dirLight.castShadow = true;
    dirLight.shadow.mapSize.width = 2048;
    dirLight.shadow.mapSize.height = 2048;
    dirLight.shadow.camera.near = 0.5;
    dirLight.shadow.camera.far = 70;
    dirLight.shadow.camera.left = -22;
    dirLight.shadow.camera.right = 22;
    dirLight.shadow.camera.top = 22;
    dirLight.shadow.camera.bottom = -22;
    dirLight.shadow.bias = -0.0005;
    this.scene.add(dirLight);

    // Secondary fill light (soft blue from opposite side)
    const fillLight = new THREE.DirectionalLight(0x38bdf8, 0.45);
    fillLight.position.set(-18, 14, -16);
    this.scene.add(fillLight);

    // Zone Accent Lights
    // 1. War Room central cyan pointlight
    const warRoomLight = new THREE.PointLight(0x00f5ff, 2.0, 10, 1.2);
    warRoomLight.position.set(0, 2.2, 0);
    this.scene.add(warRoomLight);

    // 2. Server Room cyber blue pointlight
    const serverLight = new THREE.PointLight(0x3b82f6, 1.8, 9, 1.5);
    serverLight.position.set(-10.5, 2.5, 6.5);
    this.scene.add(serverLight);

    // 3. Coffee Break warm amber light
    const coffeeLight = new THREE.PointLight(0xf59e0b, 1.5, 8, 1.4);
    coffeeLight.position.set(-10.5, 2.2, -6.5);
    this.scene.add(coffeeLight);
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 3D OFFICE ENVIRONMENT (Claw3D Architecture)
  // ═══════════════════════════════════════════════════════════════════════════
  private buildOfficeEnvironment(): void {
    // 1. Main Office Base Platform
    const floorPlateGeo = new THREE.BoxGeometry(32, 0.8, 22);
    const floorPlateMat = new THREE.MeshStandardMaterial({
      color: 0x111827,
      roughness: 0.8,
      metalness: 0.1
    });
    const floorPlate = new THREE.Mesh(floorPlateGeo, floorPlateMat);
    floorPlate.position.set(0, -0.4, 0);
    floorPlate.receiveShadow = true;
    this.scene.add(floorPlate);

    // 2. Floor Parquet / Tiles & Inlays
    // Central War Room wood circle inlay
    const circleGeo = new THREE.CylinderGeometry(4.8, 4.8, 0.05, 36);
    const circleMat = new THREE.MeshStandardMaterial({
      color: 0x1e293b,
      roughness: 0.5,
      metalness: 0.2
    });
    const warRoomFloor = new THREE.Mesh(circleGeo, circleMat);
    warRoomFloor.position.set(0, 0.02, 0);
    warRoomFloor.receiveShadow = true;
    this.scene.add(warRoomFloor);

    // Break Room cozy wood plank floor
    const loungeFloorGeo = new THREE.BoxGeometry(9.5, 0.04, 7.5);
    const loungeFloorMat = new THREE.MeshStandardMaterial({
      color: 0x27272a,
      roughness: 0.7,
      metalness: 0.1
    });
    const loungeFloor = new THREE.Mesh(loungeFloorGeo, loungeFloorMat);
    loungeFloor.position.set(-10.5, 0.02, -6.5);
    loungeFloor.receiveShadow = true;
    this.scene.add(loungeFloor);

    // Server Room metallic grid floor
    const serverFloorGeo = new THREE.BoxGeometry(9.5, 0.04, 7.5);
    const serverFloorMat = new THREE.MeshStandardMaterial({
      color: 0x0f172a,
      roughness: 0.3,
      metalness: 0.6
    });
    const serverFloor = new THREE.Mesh(serverFloorGeo, serverFloorMat);
    serverFloor.position.set(-10.5, 0.02, 6.5);
    serverFloor.receiveShadow = true;
    this.scene.add(serverFloor);

    // Fine tech grid lines across entire floor
    const gridHelper = new THREE.GridHelper(30, 30, 0x334155, 0x1e293b);
    gridHelper.position.set(0, 0.05, 0);
    this.scene.add(gridHelper);

    // 3. Modern Low Glass Walls / Partitions & Chrome Posts
    this.buildOfficePerimeter();

    // 4. Central War Room (Conference Table, Hologram Projector, Chairs)
    this.buildWarRoom();

    // 5. Coffee Lounge & Break Room (Espresso machine, mugs, couch, water cooler)
    this.buildBreakRoom();

    // 6. DevOps Server Racks (Blinking LEDs, Server blades)
    this.buildServerRoom();

    // 7. Arcade Cabinet Corner
    this.buildArcadeCorner();

    // 8. Whiteboard & Library
    this.buildWhiteboardAndLibrary();

    // 9. Modern Foliage / Potted Tropical Plants
    this.addOfficePlants();
  }

  private buildOfficePerimeter(): void {
    const wallMat = new THREE.MeshStandardMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.18,
      roughness: 0.1,
      metalness: 0.8
    });
    const frameMat = new THREE.MeshStandardMaterial({
      color: 0x334155,
      roughness: 0.4,
      metalness: 0.6
    });

    // Back wall glass panels (Z = -10.8)
    const backWallGeo = new THREE.BoxGeometry(31.6, 2.2, 0.12);
    const backWall = new THREE.Mesh(backWallGeo, wallMat);
    backWall.position.set(0, 1.1, -10.8);
    this.scene.add(backWall);

    // Back wall top & bottom rail
    const railGeo = new THREE.BoxGeometry(31.8, 0.1, 0.2);
    const railTop = new THREE.Mesh(railGeo, frameMat);
    railTop.position.set(0, 2.2, -10.8);
    this.scene.add(railTop);

    // Left wall glass panels (X = -15.8)
    const leftWallGeo = new THREE.BoxGeometry(0.12, 2.2, 21.6);
    const leftWall = new THREE.Mesh(leftWallGeo, wallMat);
    leftWall.position.set(-15.8, 1.1, 0);
    this.scene.add(leftWall);

    const leftRailTop = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.1, 21.8), frameMat);
    leftRailTop.position.set(-15.8, 2.2, 0);
    this.scene.add(leftRailTop);
  }

  private buildWarRoom(): void {
    const group = new THREE.Group();

    // Conference Table (Sleek dark pill/oval table)
    const tableTopGeo = new THREE.CylinderGeometry(2.5, 2.5, 0.15, 32);
    const tableTopMat = new THREE.MeshStandardMaterial({
      color: 0x1e293b,
      roughness: 0.25,
      metalness: 0.5
    });
    const tableTop = new THREE.Mesh(tableTopGeo, tableTopMat);
    tableTop.position.set(0, 1.1, 0);
    tableTop.castShadow = true;
    tableTop.receiveShadow = true;
    group.add(tableTop);

    // Chrome central table pedestal
    const pedestalGeo = new THREE.CylinderGeometry(0.5, 0.9, 1.1, 24);
    const chromeMat = new THREE.MeshStandardMaterial({
      color: 0x94a3b8,
      roughness: 0.2,
      metalness: 0.8
    });
    const pedestal = new THREE.Mesh(pedestalGeo, chromeMat);
    pedestal.position.set(0, 0.55, 0);
    pedestal.castShadow = true;
    group.add(pedestal);

    // Hologram Projector in table center
    const emitterRingGeo = new THREE.RingGeometry(0.6, 0.8, 24);
    const emitterRingMat = new THREE.MeshBasicMaterial({
      color: 0x00f5ff,
      side: THREE.DoubleSide
    });
    const emitterRing = new THREE.Mesh(emitterRingGeo, emitterRingMat);
    emitterRing.rotation.x = -Math.PI / 2;
    emitterRing.position.set(0, 1.18, 0);
    group.add(emitterRing);

    // Rotating 3D Hologram Prism floating above table
    const holoGeo = new THREE.OctahedronGeometry(0.45, 0);
    const holoMat = new THREE.MeshBasicMaterial({
      color: 0x00f5ff,
      wireframe: true,
      transparent: true,
      opacity: 0.85
    });
    const holoPrism = new THREE.Mesh(holoGeo, holoMat);
    holoPrism.position.set(0, 2.0, 0);
    group.add(holoPrism);

    // Floating outer ring around hologram
    const holoRingGeo = new THREE.TorusGeometry(0.7, 0.02, 8, 32);
    const holoRingMat = new THREE.MeshBasicMaterial({ color: 0x38bdf8 });
    const holoRing = new THREE.Mesh(holoRingGeo, holoRingMat);
    holoRing.position.set(0, 2.0, 0);
    holoRing.rotation.x = Math.PI / 4;
    group.add(holoRing);

    this.animatedProps.push({
      mesh: holoPrism,
      update: (t) => {
        holoPrism.rotation.y = t * 1.2;
        holoPrism.rotation.x = Math.sin(t * 0.8) * 0.2;
        holoPrism.position.y = 2.0 + Math.sin(t * 1.8) * 0.08;
        holoRing.rotation.z = -t * 0.9;
        holoRing.position.y = 2.0 + Math.sin(t * 1.8) * 0.08;
      }
    });

    // 8 Conference Chairs surrounding table
    const chairCount = 8;
    for (let i = 0; i < chairCount; i++) {
      const angle = (i / chairCount) * Math.PI * 2;
      const chairX = Math.cos(angle) * 3.1;
      const chairZ = Math.sin(angle) * 3.1;

      const chair = this.createOfficeChair(0x334155);
      chair.position.set(chairX, 0, chairZ);
      chair.rotation.y = Math.atan2(-chairX, -chairZ);
      group.add(chair);
    }

    this.scene.add(group);
  }

  private buildBreakRoom(): void {
    const group = new THREE.Group();
    group.position.set(-10.5, 0, -6.5);

    // Coffee Counter Bar
    const counterGeo = new THREE.BoxGeometry(4.0, 1.2, 1.2);
    const counterMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.3 });
    const counter = new THREE.Mesh(counterGeo, counterMat);
    counter.position.set(0, 0.6, -1.8);
    counter.castShadow = true;
    counter.receiveShadow = true;
    group.add(counter);

    // High-tech Espresso Machine
    const machineBodyGeo = new THREE.BoxGeometry(1.2, 0.8, 0.7);
    const machineMat = new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.8, roughness: 0.2 });
    const machine = new THREE.Mesh(machineBodyGeo, machineMat);
    machine.position.set(-0.6, 1.6, -1.8);
    machine.castShadow = true;
    group.add(machine);

    // Espresso display screen
    const screenGeo = new THREE.PlaneGeometry(0.35, 0.2);
    const screenMat = new THREE.MeshBasicMaterial({ color: 0x10b981 });
    const screen = new THREE.Mesh(screenGeo, screenMat);
    screen.position.set(-0.6, 1.7, -1.44);
    group.add(screen);

    // Coffee Mugs
    const mugGeo = new THREE.CylinderGeometry(0.09, 0.08, 0.16, 12);
    const mugMat = new THREE.MeshStandardMaterial({ color: 0xfacc15, roughness: 0.3 });
    const mug1 = new THREE.Mesh(mugGeo, mugMat);
    mug1.position.set(0.4, 1.28, -1.7);
    group.add(mug1);

    // Water Cooler
    const waterBaseGeo = new THREE.CylinderGeometry(0.35, 0.35, 1.3, 16);
    const waterBaseMat = new THREE.MeshStandardMaterial({ color: 0xf1f5f9, roughness: 0.4 });
    const waterBase = new THREE.Mesh(waterBaseGeo, waterBaseMat);
    waterBase.position.set(2.4, 0.65, -1.8);
    waterBase.castShadow = true;
    group.add(waterBase);

    // Water bottle (blue translucent)
    const jugGeo = new THREE.CylinderGeometry(0.32, 0.32, 0.75, 16);
    const jugMat = new THREE.MeshStandardMaterial({
      color: 0x38bdf8,
      transparent: true,
      opacity: 0.7,
      roughness: 0.1
    });
    const jug = new THREE.Mesh(jugGeo, jugMat);
    jug.position.set(2.4, 1.65, -1.8);
    group.add(jug);

    // Lounge Sectional Sofa
    const sofaSeatGeo = new THREE.BoxGeometry(3.6, 0.5, 1.4);
    const sofaMat = new THREE.MeshStandardMaterial({ color: 0x3b82f6, roughness: 0.8 });
    const sofaSeat = new THREE.Mesh(sofaSeatGeo, sofaMat);
    sofaSeat.position.set(-0.2, 0.35, 1.5);
    sofaSeat.castShadow = true;
    group.add(sofaSeat);

    const sofaBackGeo = new THREE.BoxGeometry(3.6, 0.8, 0.4);
    const sofaBack = new THREE.Mesh(sofaBackGeo, sofaMat);
    sofaBack.position.set(-0.2, 0.85, 2.0);
    sofaBack.castShadow = true;
    group.add(sofaBack);

    // Coffee Table in front of couch
    const coffeeTableGeo = new THREE.BoxGeometry(2.4, 0.45, 1.0);
    const coffeeTableMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.4, metalness: 0.3 });
    const coffeeTable = new THREE.Mesh(coffeeTableGeo, coffeeTableMat);
    coffeeTable.position.set(-0.2, 0.22, 0.2);
    coffeeTable.castShadow = true;
    group.add(coffeeTable);

    this.scene.add(group);
  }

  private buildServerRoom(): void {
    const group = new THREE.Group();
    group.position.set(-10.5, 0, 6.5);

    // 2 Server Racks
    for (let r = 0; r < 2; r++) {
      const rackX = (r - 0.5) * 2.2;
      const rackGeo = new THREE.BoxGeometry(1.6, 3.2, 1.2);
      const rackMat = new THREE.MeshStandardMaterial({
        color: 0x0f172a,
        metalness: 0.7,
        roughness: 0.3
      });
      const rack = new THREE.Mesh(rackGeo, rackMat);
      rack.position.set(rackX, 1.6, 0);
      rack.castShadow = true;
      group.add(rack);

      // Server rack blades with LEDs
      for (let b = 0; b < 6; b++) {
        const bladeY = 0.5 + b * 0.42;

        const ledMat1 = new THREE.MeshBasicMaterial({ color: 0x10b981 });
        const led1 = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 0.02), ledMat1);
        led1.position.set(rackX - 0.4, bladeY, 0.61);
        group.add(led1);

        const ledMat2 = new THREE.MeshBasicMaterial({ color: 0x3b82f6 });
        const led2 = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.06, 0.02), ledMat2);
        led2.position.set(rackX - 0.25, bladeY, 0.61);
        group.add(led2);

        // Pulsating LED animation
        this.animatedProps.push({
          mesh: led1,
          update: (t) => {
            const flicker = Math.sin(t * 8 + b * 2 + r) > 0 ? 0x10b981 : 0x064e3b;
            ledMat1.color.setHex(flicker);
          }
        });
      }
    }

    this.scene.add(group);
  }

  private buildArcadeCorner(): void {
    const group = new THREE.Group();
    group.position.set(-10.5, 0, 0.5);

    // Arcade Body
    const cabinetGeo = new THREE.BoxGeometry(1.2, 2.5, 1.1);
    const cabinetMat = new THREE.MeshStandardMaterial({ color: 0x7c3aed, roughness: 0.4 });
    const cabinet = new THREE.Mesh(cabinetGeo, cabinetMat);
    cabinet.position.set(0, 1.25, 0);
    cabinet.castShadow = true;
    group.add(cabinet);

    // Glowing Marquee Header
    const marqueeGeo = new THREE.BoxGeometry(1.1, 0.3, 0.1);
    const marqueeMat = new THREE.MeshBasicMaterial({ color: 0xf43f5e });
    const marquee = new THREE.Mesh(marqueeGeo, marqueeMat);
    marquee.position.set(0, 2.25, 0.56);
    group.add(marquee);

    // Arcade CRT Screen
    const screenGeo = new THREE.PlaneGeometry(0.9, 0.7);
    const screenMat = new THREE.MeshBasicMaterial({ color: 0x06b6d4 });
    const screen = new THREE.Mesh(screenGeo, screenMat);
    screen.position.set(0, 1.55, 0.56);
    screen.rotation.x = -0.25;
    group.add(screen);

    this.animatedProps.push({
      mesh: screen,
      update: (t) => {
        const pulse = (Math.sin(t * 6) * 0.2 + 0.8);
        screenMat.color.setRGB(0.05 * pulse, 0.7 * pulse, 0.9 * pulse);
      }
    });

    this.scene.add(group);
  }

  private buildWhiteboardAndLibrary(): void {
    // 1. Whiteboard at back wall (-1, 0, -10.4)
    const wbGroup = new THREE.Group();
    wbGroup.position.set(-1, 0, -10.4);

    const boardGeo = new THREE.BoxGeometry(4.2, 2.2, 0.08);
    const boardMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.1 });
    const board = new THREE.Mesh(boardGeo, boardMat);
    board.position.set(0, 1.8, 0);
    board.castShadow = true;
    wbGroup.add(board);

    // Frame
    const frameGeo = new THREE.BoxGeometry(4.3, 2.3, 0.06);
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x475569, metalness: 0.5 });
    const frame = new THREE.Mesh(frameGeo, frameMat);
    frame.position.set(0, 1.8, -0.02);
    wbGroup.add(frame);

    this.scene.add(wbGroup);

    // 2. Bookshelf (Library) at (4.5, 0, -10.4)
    const libGroup = new THREE.Group();
    libGroup.position.set(4.5, 0, -10.4);

    const shelfGeo = new THREE.BoxGeometry(3.2, 2.4, 0.6);
    const shelfMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.6 });
    const shelf = new THREE.Mesh(shelfGeo, shelfMat);
    shelf.position.set(0, 1.2, 0);
    shelf.castShadow = true;
    libGroup.add(shelf);

    // Colored books rows
    const bookColors = [0xef4444, 0x3b82f6, 0x10b981, 0xfacc15, 0x8b5cf6, 0x06b6d4];
    for (let i = 0; i < 14; i++) {
      const bookGeo = new THREE.BoxGeometry(0.14, 0.45, 0.4);
      const bookMat = new THREE.MeshStandardMaterial({ color: bookColors[i % bookColors.length] });
      const book = new THREE.Mesh(bookGeo, bookMat);
      book.position.set(-1.2 + i * 0.18, 1.5, 0.05);
      libGroup.add(book);
    }

    this.scene.add(libGroup);
  }

  private addOfficePlants(): void {
    const plantPositions = [
      new THREE.Vector3(-14, 0, -9.5),
      new THREE.Vector3(-14, 0, 9.5),
      new THREE.Vector3(14, 0, -9.5),
      new THREE.Vector3(14, 0, 9.5),
      new THREE.Vector3(-5.5, 0, -10.2)
    ];

    plantPositions.forEach((pos) => {
      const plantGroup = new THREE.Group();
      plantGroup.position.copy(pos);

      // White ceramic pot
      const potGeo = new THREE.CylinderGeometry(0.4, 0.3, 0.9, 16);
      const potMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.2 });
      const pot = new THREE.Mesh(potGeo, potMat);
      pot.position.y = 0.45;
      pot.castShadow = true;
      plantGroup.add(pot);

      // Leaves / foliage
      const foliageGeo = new THREE.DodecahedronGeometry(0.65, 1);
      const foliageMat = new THREE.MeshStandardMaterial({ color: 0x15803d, roughness: 0.7 });
      const foliage = new THREE.Mesh(foliageGeo, foliageMat);
      foliage.position.y = 1.25;
      foliage.castShadow = true;
      plantGroup.add(foliage);

      this.scene.add(plantGroup);
    });
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 3D WORKSTATION GENERATOR (Desk + Chair + Dual Glowing Monitors)
  // ═══════════════════════════════════════════════════════════════════════════
  private createWorkstation(agentId: string, colorHex: number): THREE.Group {
    const group = new THREE.Group();
    group.userData = { isDesk: true, agentId };

    // 1. Desk Surface (Solid oak/walnut)
    const deskTopGeo = new THREE.BoxGeometry(2.2, 0.1, 1.2);
    const deskTopMat = new THREE.MeshStandardMaterial({
      color: 0x1e293b,
      roughness: 0.35,
      metalness: 0.2
    });
    const deskTop = new THREE.Mesh(deskTopGeo, deskTopMat);
    deskTop.position.set(0, 1.05, 0);
    deskTop.castShadow = true;
    deskTop.receiveShadow = true;
    group.add(deskTop);

    // Matte black steel legs
    const legGeo = new THREE.CylinderGeometry(0.04, 0.04, 1.05, 12);
    const legMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, metalness: 0.8, roughness: 0.3 });
    const legPositions = [
      [-0.95, 0.525, -0.45],
      [0.95, 0.525, -0.45],
      [-0.95, 0.525, 0.45],
      [0.95, 0.525, 0.45]
    ];
    legPositions.forEach(([x, y, z]) => {
      const leg = new THREE.Mesh(legGeo, legMat);
      leg.position.set(x, y, z);
      leg.castShadow = true;
      group.add(leg);
    });

    // 2. Dual Angled Monitors
    // Left Monitor (Ultrawide code terminal)
    const mon1Geo = new THREE.BoxGeometry(0.85, 0.5, 0.04);
    const monBezelMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.3 });
    const mon1 = new THREE.Mesh(mon1Geo, monBezelMat);
    mon1.position.set(-0.42, 1.48, -0.25);
    mon1.rotation.y = 0.18;
    mon1.castShadow = true;
    group.add(mon1);

    const screen1Geo = new THREE.PlaneGeometry(0.8, 0.44);
    const screen1Mat = new THREE.MeshBasicMaterial({ color: 0x06b6d4 });
    const screen1 = new THREE.Mesh(screen1Geo, screen1Mat);
    screen1.position.set(-0.42, 1.48, -0.228);
    screen1.rotation.y = 0.18;
    group.add(screen1);

    // Right Monitor (Diagnostics / UI preview)
    const mon2Geo = new THREE.BoxGeometry(0.85, 0.5, 0.04);
    const mon2 = new THREE.Mesh(mon2Geo, monBezelMat);
    mon2.position.set(0.42, 1.48, -0.25);
    mon2.rotation.y = -0.18;
    mon2.castShadow = true;
    group.add(mon2);

    const screen2Geo = new THREE.PlaneGeometry(0.8, 0.44);
    const screen2Mat = new THREE.MeshBasicMaterial({ color: colorHex });
    const screen2 = new THREE.Mesh(screen2Geo, screen2Mat);
    screen2.position.set(0.42, 1.48, -0.228);
    screen2.rotation.y = -0.18;
    group.add(screen2);

    // 3. Backlit Keyboard & Mouse
    const kbGeo = new THREE.BoxGeometry(0.65, 0.02, 0.22);
    const kbMat = new THREE.MeshStandardMaterial({ color: 0x0f172a });
    const kb = new THREE.Mesh(kbGeo, kbMat);
    kb.position.set(0, 1.11, 0.18);
    group.add(kb);

    const mouseGeo = new THREE.BoxGeometry(0.08, 0.03, 0.12);
    const mouseMat = new THREE.MeshStandardMaterial({ color: 0x475569 });
    const mouse = new THREE.Mesh(mouseGeo, mouseMat);
    mouse.position.set(0.48, 1.11, 0.18);
    group.add(mouse);

    // 4. Desk Underglow LED Strip
    const stripGeo = new THREE.BoxGeometry(2.0, 0.02, 0.02);
    const stripMat = new THREE.MeshBasicMaterial({ color: colorHex });
    const strip = new THREE.Mesh(stripGeo, stripMat);
    strip.position.set(0, 1.0, 0.58);
    group.add(strip);

    // 5. Ergonomic Swivel Chair
    const chair = this.createOfficeChair(colorHex);
    chair.position.set(0, 0, 0.85);
    chair.rotation.y = Math.PI;
    group.add(chair);

    // Screen pulsating animation while working
    this.animatedProps.push({
      mesh: screen1,
      update: (t) => {
        const agentGroup = this.agentMeshes.get(agentId);
        const isWorking = agentGroup?.userData?.['status'] === 'WORKING';
        if (isWorking) {
          const glow = Math.sin(t * 12) * 0.3 + 0.7;
          screen1Mat.color.setRGB(0.05 * glow, 0.8 * glow, 0.9 * glow);
        } else {
          screen1Mat.color.setHex(0x1e293b);
        }
      }
    });

    return group;
  }

  private createOfficeChair(accentColorHex: number): THREE.Group {
    const chair = new THREE.Group();

    // Seat cushion
    const seatGeo = new THREE.BoxGeometry(0.7, 0.12, 0.65);
    const seatMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.8 });
    const seat = new THREE.Mesh(seatGeo, seatMat);
    seat.position.y = 0.65;
    seat.castShadow = true;
    chair.add(seat);

    // Curved Backrest
    const backGeo = new THREE.BoxGeometry(0.65, 0.8, 0.1);
    const backMat = new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.6 });
    const back = new THREE.Mesh(backGeo, backMat);
    back.position.set(0, 1.15, -0.3);
    back.rotation.x = -0.1;
    back.castShadow = true;
    chair.add(back);

    // Gas lift pole
    const poleGeo = new THREE.CylinderGeometry(0.05, 0.05, 0.5, 12);
    const chromeMat = new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.9 });
    const pole = new THREE.Mesh(poleGeo, chromeMat);
    pole.position.y = 0.3;
    chair.add(pole);

    // 5-Star Caster Base
    const starGeo = new THREE.CylinderGeometry(0.35, 0.35, 0.06, 5);
    const star = new THREE.Mesh(starGeo, chromeMat);
    star.position.y = 0.08;
    chair.add(star);

    return chair;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 3D AGENT CHARACTER GENERATOR (Claw3D Voxel/Low-Poly Humanoids)
  // ═══════════════════════════════════════════════════════════════════════════
  public syncAgents(agentList: Agent3DData[]): void {
    agentList.forEach((data) => {
      const colorHex = parseInt(data.color.replace('#', '0x'), 16);

      // Create or update Desk
      if (!this.deskMeshes.has(data.id)) {
        const deskConfig = this.deskPositions[data.id] || { x: 7, z: 0, rotY: 0 };
        const deskGroup = this.createWorkstation(data.id, colorHex);
        deskGroup.position.set(deskConfig.x, 0, deskConfig.z);
        deskGroup.rotation.y = deskConfig.rotY;
        this.scene.add(deskGroup);
        this.deskMeshes.set(data.id, deskGroup);
      }

      // Create or update Agent 3D Character
      let agentGroup = this.agentMeshes.get(data.id);
      if (!agentGroup) {
        agentGroup = this.createAgentCharacter(data, colorHex);
        this.scene.add(agentGroup);
        this.agentMeshes.set(data.id, agentGroup);

        // Initial position at desk chair facing keyboard/monitors
        const deskConfig = this.deskPositions[data.id];
        if (deskConfig) {
          agentGroup.position.set(deskConfig.x - 0.82, 0, deskConfig.z);
          agentGroup.rotation.y = Math.PI / 2;
        }
      }

      // Update state metadata
      agentGroup.userData['status'] = data.status;
      agentGroup.userData['idleState'] = data.idleState;
      agentGroup.userData['idleMessage'] = data.idleMessage;
      agentGroup.userData['isJumping'] = data.isJumping;
      agentGroup.userData['name'] = data.name;
      agentGroup.userData['role'] = data.role;

      // Update Selection Ring visibility
      const ring = agentGroup.getObjectByName('selectionRing');
      if (ring) {
        ring.visible = this.selectedAgentId === data.id;
      }

      // Target position resolution
      this.updateAgentTarget(agentGroup, data);
    });
  }

  private createAgentCharacter(data: Agent3DData, colorHex: number): THREE.Group {
    const root = new THREE.Group();
    root.userData = { isAgent: true, agentId: data.id };

    // 1. Floor Drop Shadow Disc
    const shadowGeo = new THREE.CircleGeometry(0.45, 16);
    const shadowMat = new THREE.MeshBasicMaterial({
      color: 0x000000,
      transparent: true,
      opacity: 0.4
    });
    const shadow = new THREE.Mesh(shadowGeo, shadowMat);
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = 0.02;
    root.add(shadow);

    // 2. Selection Ring (Glowing ring on floor)
    const ringGeo = new THREE.RingGeometry(0.55, 0.65, 32);
    const ringMat = new THREE.MeshBasicMaterial({
      color: colorHex,
      side: THREE.DoubleSide
    });
    const selectionRing = new THREE.Mesh(ringGeo, ringMat);
    selectionRing.name = 'selectionRing';
    selectionRing.rotation.x = -Math.PI / 2;
    selectionRing.position.y = 0.03;
    selectionRing.visible = false;
    root.add(selectionRing);

    // 3. Animated Body Container (Bobs, walks, jumps)
    const body = new THREE.Group();
    body.name = 'body';
    body.position.y = 0;
    root.add(body);

    // Skin & Clothing Materials
    const skinMat = new THREE.MeshStandardMaterial({ color: 0xfcd34d, roughness: 0.5 });
    const shirtMat = new THREE.MeshStandardMaterial({
      color: colorHex,
      roughness: 0.4,
      metalness: 0.1
    });
    const pantsMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.8 });
    const shoeMat = new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.3 });

    // Torso (Stylized hoodie/jacket)
    const torsoGeo = new THREE.BoxGeometry(0.58, 0.65, 0.36);
    const torso = new THREE.Mesh(torsoGeo, shirtMat);
    torso.position.y = 1.05;
    torso.castShadow = true;
    body.add(torso);

    // Head
    const headGeo = new THREE.BoxGeometry(0.48, 0.48, 0.44);
    const head = new THREE.Mesh(headGeo, skinMat);
    head.name = 'head';
    head.position.y = 1.65;
    head.castShadow = true;
    body.add(head);

    // Cyber Visor / Glasses / Hair based on role
    this.addRoleAccessories(head, data.id, colorHex);

    // Left Arm Pivot & Mesh
    const armGeo = new THREE.BoxGeometry(0.16, 0.55, 0.16);
    const leftArmPivot = new THREE.Group();
    leftArmPivot.name = 'leftArmPivot';
    leftArmPivot.position.set(-0.38, 1.3, 0);
    const leftArm = new THREE.Mesh(armGeo, shirtMat);
    leftArm.position.y = -0.22;
    leftArm.castShadow = true;
    leftArmPivot.add(leftArm);
    body.add(leftArmPivot);

    // Right Arm Pivot & Mesh
    const rightArmPivot = new THREE.Group();
    rightArmPivot.name = 'rightArmPivot';
    rightArmPivot.position.set(0.38, 1.3, 0);
    const rightArm = new THREE.Mesh(armGeo, shirtMat);
    rightArm.position.y = -0.22;
    rightArm.castShadow = true;
    rightArmPivot.add(rightArm);
    body.add(rightArmPivot);

    // Left Leg Pivot & Mesh
    const legGeo = new THREE.BoxGeometry(0.18, 0.55, 0.2);
    const leftLegPivot = new THREE.Group();
    leftLegPivot.name = 'leftLegPivot';
    leftLegPivot.position.set(-0.16, 0.65, 0);
    const leftLeg = new THREE.Mesh(legGeo, pantsMat);
    leftLeg.position.y = -0.25;
    leftLeg.castShadow = true;
    leftLegPivot.add(leftLeg);
    body.add(leftLegPivot);

    // Right Leg Pivot & Mesh
    const rightLegPivot = new THREE.Group();
    rightLegPivot.name = 'rightLegPivot';
    rightLegPivot.position.set(0.16, 0.65, 0);
    const rightLeg = new THREE.Mesh(legGeo, pantsMat);
    rightLeg.position.y = -0.25;
    rightLeg.castShadow = true;
    rightLegPivot.add(rightLeg);
    body.add(rightLegPivot);

    return root;
  }

  private addRoleAccessories(head: THREE.Mesh, role: string, colorHex: number): void {
    if (role === 'DevOps') {
      // DJ Headphones
      const hpBandGeo = new THREE.TorusGeometry(0.28, 0.04, 8, 16, Math.PI);
      const hpBand = new THREE.Mesh(hpBandGeo, new THREE.MeshStandardMaterial({ color: 0x0f172a }));
      hpBand.rotation.x = -Math.PI / 2;
      hpBand.position.y = 0.22;
      head.add(hpBand);

      const earGeo = new THREE.CylinderGeometry(0.1, 0.1, 0.08, 12);
      const earMat = new THREE.MeshStandardMaterial({ color: colorHex });
      const earL = new THREE.Mesh(earGeo, earMat);
      earL.rotation.z = Math.PI / 2;
      earL.position.set(-0.25, 0, 0);
      head.add(earL);

      const earR = new THREE.Mesh(earGeo, earMat);
      earR.rotation.z = Math.PI / 2;
      earR.position.set(0.25, 0, 0);
      head.add(earR);
    } else if (role === 'Security') {
      // Cyber Shades / Visor
      const visorGeo = new THREE.BoxGeometry(0.44, 0.12, 0.06);
      const visorMat = new THREE.MeshBasicMaterial({ color: 0xef4444 });
      const visor = new THREE.Mesh(visorGeo, visorMat);
      visor.position.set(0, 0.05, 0.23);
      head.add(visor);
    } else if (role === 'TeamLead') {
      // Golden Headset / Crown Band
      const bandGeo = new THREE.BoxGeometry(0.5, 0.06, 0.46);
      const bandMat = new THREE.MeshStandardMaterial({ color: 0xfacc15, metalness: 0.8 });
      const band = new THREE.Mesh(bandGeo, bandMat);
      band.position.y = 0.22;
      head.add(band);
    } else {
      // Stylized Cyber Visor
      const visorGeo = new THREE.BoxGeometry(0.42, 0.1, 0.05);
      const visorMat = new THREE.MeshBasicMaterial({ color: colorHex });
      const visor = new THREE.Mesh(visorGeo, visorMat);
      visor.position.set(0, 0.04, 0.23);
      head.add(visor);
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // AGENT TARGET & MOVEMENT INTERPOLATION
  // ═══════════════════════════════════════════════════════════════════════════
  // Calculates clean waypoint corridors avoiding walking straight through War Room glass cylinder
  private generateNavPath(start: THREE.Vector3, end: THREE.Vector3): THREE.Vector3[] {
    const dist = Math.hypot(end.x - start.x, end.z - start.z);
    if (dist < 0.4) {
      return [end.clone()];
    }

    // Check if straight line between start and end passes near War Room center (0, 0)
    const dx = end.x - start.x;
    const dz = end.z - start.z;
    const lenSq = dx * dx + dz * dz;
    const t = Math.max(0, Math.min(1, -(start.x * dx + start.z * dz) / lenSq));
    const closestX = start.x + t * dx;
    const closestZ = start.z + t * dz;
    const distToCenter = Math.hypot(closestX, closestZ);

    // If straight trajectory cuts through central War Room (radius 4.2m)
    if (distToCenter < 4.2) {
      // Choose corridor: North (Z = -5.4) or South (Z = 5.0) based on positions
      const corridorZ = (start.z + end.z) < 0 ? -5.4 : 5.0;
      const startSideX = start.x > 0 ? 4.8 : -4.8;
      const endSideX = end.x > 0 ? 4.8 : -4.8;

      const waypoints: THREE.Vector3[] = [];

      // Step 1: Walk out of desk pod / room to the aisle
      if (Math.abs(start.z - corridorZ) > 1.2) {
        waypoints.push(new THREE.Vector3(startSideX, 0, corridorZ));
      }

      // Step 2: Walk along corridor past War Room to destination side
      if (Math.sign(startSideX) !== Math.sign(endSideX)) {
        waypoints.push(new THREE.Vector3(endSideX, 0, corridorZ));
      }

      // Step 3: Final destination
      waypoints.push(end.clone());
      return waypoints;
    }

    return [end.clone()];
  }

  private updateAgentTarget(agentGroup: THREE.Group, data: Agent3DData): void {
    const isWorking = data.status === 'WORKING';
    const isCompleted = data.status === 'COMPLETED';

    let targetX = 0;
    let targetZ = 0;
    let targetRotY = 0;
    let isZoneSeated = false;

    if (data.convPosition && !isWorking) {
      // Dynamic Conversation Group (Face-to-Face or Circle Formation)
      targetX = data.convPosition.x;
      targetZ = data.convPosition.z;
      targetRotY = data.convPosition.rotY;
      isZoneSeated = false;
    } else if (isWorking || (!data.idleState && (isCompleted || data.status === 'IDLE'))) {
      // At designated desk - seated in chair facing monitors
      const desk = this.deskPositions[data.id];
      if (desk) {
        targetX = desk.x - 0.82;
        targetZ = desk.z;
        targetRotY = Math.PI / 2;
        isZoneSeated = true;
      }
    } else if (data.idleState === 'MEETING') {
      // In War Room around conference table
      const seat = this.meetingSeats[data.id] || new THREE.Vector3(0, 0, 0);
      targetX = seat.x;
      targetZ = seat.z;
      targetRotY = Math.atan2(-seat.x, -seat.z);
      isZoneSeated = true;
    } else if (data.idleState === 'WANDERING') {
      // Open floor wandering waypoints
      const hash = data.id.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
      const wp = this.wanderWaypoints[hash % this.wanderWaypoints.length];
      targetX = wp.x + ((hash % 3) - 1) * 0.45;
      targetZ = wp.z + (((hash * 7) % 3) - 1) * 0.45;
      targetRotY = (hash % 8) * (Math.PI / 4);
    } else if (data.idleState && this.zoneCoords[data.idleState]) {
      const zone = this.zoneCoords[data.idleState];
      const hash = data.id.split('').reduce((acc, c) => acc + c.charCodeAt(0), 0);
      const offsetX = ((hash % 5) - 2) * 0.35;
      const offsetZ = (((hash * 3) % 5) - 2) * 0.35;
      targetX = zone.pos.x + offsetX;
      targetZ = zone.pos.z + offsetZ;
      targetRotY = zone.rotY;
      isZoneSeated = !!zone.isSeated;
    } else {
      // Default to desk chair
      const desk = this.deskPositions[data.id];
      if (desk) {
        targetX = desk.x - 0.82;
        targetZ = desk.z;
        targetRotY = Math.PI / 2;
        isZoneSeated = true;
      }
    }

    const prevTargetX = agentGroup.userData['targetX'];
    const prevTargetZ = agentGroup.userData['targetZ'];
    const hasExistingTarget = prevTargetX !== undefined;
    const targetChanged = !hasExistingTarget || Math.hypot(targetX - prevTargetX, targetZ - prevTargetZ) > 0.35;

    if (targetChanged) {
      agentGroup.userData['targetX'] = targetX;
      agentGroup.userData['targetZ'] = targetZ;
      agentGroup.userData['targetRotY'] = targetRotY;
      agentGroup.userData['isZoneSeated'] = isZoneSeated;

      if (hasExistingTarget) {
        // Build corridor-aware navigation path
        const startPos = new THREE.Vector3(agentGroup.position.x, 0, agentGroup.position.z);
        const endPos = new THREE.Vector3(targetX, 0, targetZ);
        agentGroup.userData['navPath'] = this.generateNavPath(startPos, endPos);
      } else {
        // Initial spawn
        agentGroup.userData['navPath'] = [];
        agentGroup.position.set(targetX, 0, targetZ);
        agentGroup.rotation.y = targetRotY;
        agentGroup.userData['seatedBlend'] = isZoneSeated ? 1.0 : 0.0;
      }
    }
  }

  private animate(timestamp: number): void {
    this.reqId = requestAnimationFrame((t) => this.animate(t));

    const time = timestamp * 0.001;

    // 1. Controls update (damping)
    this.controls.update();

    // 2. Camera smooth transition
    if (this.isCameraTransitioning) {
      this.camTransitionProgress += 0.035 * this.camTransitionSpeed;
      if (this.camTransitionProgress >= 1) {
        this.camTransitionProgress = 1;
        this.isCameraTransitioning = false;
      }
      const ease = this.easeInOutQuad(this.camTransitionProgress);
      this.camera.position.lerpVectors(this.camStartPos, this.camEndPos, ease);
      this.controls.target.lerpVectors(this.targetStartPos, this.targetEndPos, ease);
    }

    // 3. Update animated props (hologram, screens, server LEDs)
    for (const prop of this.animatedProps) {
      prop.update(time);
    }

    const dt = this.lastFrameTime > 0 ? Math.min(0.06, Math.max(0.001, time - this.lastFrameTime)) : 0.016;
    this.lastFrameTime = time;

    // 4. Update Agents (human locomotion kinematics & character animations)
    this.agentMeshes.forEach((agentGroup) => {
      this.updateAgentFrame(agentGroup, time, dt);
    });

    // 5. Render Scene
    this.renderer.render(this.scene, this.camera);
  }

  private updateAgentFrame(agentGroup: THREE.Group, time: number, dt: number): void {
    const path: THREE.Vector3[] = agentGroup.userData['navPath'] || [];
    const targetRotY = agentGroup.userData['targetRotY'] ?? agentGroup.rotation.y;
    const isWorking = agentGroup.userData['status'] === 'WORKING';
    const isJumping = agentGroup.userData['isJumping'];
    const idleState = agentGroup.userData['idleState'];
    const isMeeting = idleState === 'MEETING';
    const isZoneSeated = !!agentGroup.userData['isZoneSeated'];

    let isMoving = false;
    let stepDist = 0;
    const WALK_SPEED = 2.65; // Constant brisk human walking speed (no flying or sudden acceleration)
    const TURN_SPEED = 9.5;

    // ─── 1. WAYPOINT WALKING PATH NAVIGATION ──────────────────────────
    if (path.length > 0) {
      const nextTarget = path[0];
      const dx = nextTarget.x - agentGroup.position.x;
      const dz = nextTarget.z - agentGroup.position.z;
      const distToTarget = Math.hypot(dx, dz);

      if (distToTarget < 0.22) {
        path.shift();
        if (path.length > 0) {
          isMoving = true;
        }
      } else {
        isMoving = true;
        stepDist = Math.min(distToTarget, WALK_SPEED * dt);
        agentGroup.position.x += (dx / distToTarget) * stepDist;
        agentGroup.position.z += (dz / distToTarget) * stepDist;

        // Smoothly rotate to face the exact movement direction (with angle wrap-around protection)
        const moveAngle = Math.atan2(dx, dz);
        let angleDiff = moveAngle - agentGroup.rotation.y;
        while (angleDiff < -Math.PI) angleDiff += Math.PI * 2;
        while (angleDiff > Math.PI) angleDiff -= Math.PI * 2;
        agentGroup.rotation.y += angleDiff * Math.min(1.0, TURN_SPEED * dt);

        // Advance walk phase strictly proportional to ground distance moved (Zero foot-skating!)
        agentGroup.userData['walkPhase'] = (agentGroup.userData['walkPhase'] || 0) + (stepDist * 8.5);
      }
    }

    if (!isMoving) {
      // Turn to face target orientation when arriving (towards desk, couch, person, or whiteboard)
      let turnDiff = targetRotY - agentGroup.rotation.y;
      while (turnDiff < -Math.PI) turnDiff += Math.PI * 2;
      while (turnDiff > Math.PI) turnDiff -= Math.PI * 2;
      agentGroup.rotation.y += turnDiff * Math.min(1.0, TURN_SPEED * 0.7 * dt);
    }

    // ─── 2. SEATED BLEND TRANSITION (Stand Up ↔ Sit Down) ────────────
    const targetSeated = !isMoving && (isWorking || isMeeting || isZoneSeated);
    let seatedBlend: number = agentGroup.userData['seatedBlend'] ?? (targetSeated ? 1.0 : 0.0);
    if (targetSeated) {
      seatedBlend = Math.min(1.0, seatedBlend + dt * 3.8); // Smoothly sits down in 0.26s
    } else {
      seatedBlend = Math.max(0.0, seatedBlend - dt * 4.5); // Smoothly pushes up and stands in 0.22s
    }
    agentGroup.userData['seatedBlend'] = seatedBlend;

    const body = agentGroup.getObjectByName('body');
    const leftArmPivot = agentGroup.getObjectByName('leftArmPivot') as THREE.Group;
    const rightArmPivot = agentGroup.getObjectByName('rightArmPivot') as THREE.Group;
    const leftLegPivot = agentGroup.getObjectByName('leftLegPivot') as THREE.Group;
    const rightLegPivot = agentGroup.getObjectByName('rightLegPivot') as THREE.Group;
    const head = agentGroup.getObjectByName('head') as THREE.Mesh;

    if (!body || !leftLegPivot || !rightLegPivot || !leftArmPivot || !rightArmPivot) return;

    if (isJumping) {
      // 3D Jump hop trigger
      const jumpTime = (time * 8) % Math.PI;
      body.position.y = Math.sin(jumpTime) * 0.8;
      leftArmPivot.rotation.z = Math.PI * 0.8;
      rightArmPivot.rotation.z = -Math.PI * 0.8;
      return;
    }

    // ─── 3. HUMAN WALKING KINEMATICS (Stride, Hip Sway, Foot Grounding) ─
    const walkPhase = agentGroup.userData['walkPhase'] || 0;
    const standingLegLeft = isMoving ? Math.sin(walkPhase) * 0.68 : 0;
    const standingLegRight = isMoving ? -Math.sin(walkPhase) * 0.68 : 0;

    // Realistic human pelvic bounce on each step (twice per full left/right stride cycle)
    const walkBobY = isMoving ? Math.abs(Math.sin(walkPhase)) * 0.075 : 0;
    // Lateral weight transfer sway: body tilts slightly onto the planted foot
    const hipSway = isMoving ? Math.sin(walkPhase) * 0.045 : 0;
    const hipTilt = isMoving ? Math.sin(walkPhase) * 0.035 : 0;

    // Knee bend during leg backswing to prevent clipping the ground
    const leftKneeBend = isMoving ? Math.max(0, -Math.sin(walkPhase)) * 0.35 : 0;
    const rightKneeBend = isMoving ? Math.max(0, Math.sin(walkPhase)) * 0.35 : 0;

    // Blend leg angles between walking/standing and chair seated posture
    leftLegPivot.rotation.x = THREE.MathUtils.lerp(standingLegLeft, -Math.PI / 2.2, seatedBlend);
    rightLegPivot.rotation.x = THREE.MathUtils.lerp(standingLegRight, -Math.PI / 2.2, seatedBlend);

    const leftLegMesh = leftLegPivot.children[0] as THREE.Mesh;
    const rightLegMesh = rightLegPivot.children[0] as THREE.Mesh;
    if (leftLegMesh) leftLegMesh.rotation.x = THREE.MathUtils.lerp(leftKneeBend, 0, seatedBlend);
    if (rightLegMesh) rightLegMesh.rotation.x = THREE.MathUtils.lerp(rightKneeBend, 0, seatedBlend);

    body.position.y = THREE.MathUtils.lerp(walkBobY, -0.05, seatedBlend);
    body.rotation.z = THREE.MathUtils.lerp(hipSway, 0, seatedBlend);
    body.rotation.y = THREE.MathUtils.lerp(hipTilt, 0, seatedBlend);

    // ─── 4. ARMS & UPPER BODY GESTURES ────────────────────────────────
    const hasDialogue = !!agentGroup.userData['idleMessage'];

    if (isMoving) {
      // Natural human arm swing in opposition to legs (Right arm forward when Left leg forward)
      leftArmPivot.rotation.x = -Math.sin(walkPhase) * 0.55;
      rightArmPivot.rotation.x = Math.sin(walkPhase) * 0.55;
      leftArmPivot.rotation.z = 0.08;
      rightArmPivot.rotation.z = -0.08;

      if (head) {
        head.rotation.y = Math.sin(walkPhase * 0.5) * 0.08;
        head.rotation.x = 0.04;
      }
    } else if (seatedBlend > 0.6) {
      // Seated interactions (typing, resting hands, chatting)
      if (isWorking) {
        // Rapid typing on keyboard
        const typeSpeed = time * 18;
        leftArmPivot.rotation.x = -Math.PI / 2.3 + Math.sin(typeSpeed) * 0.12;
        rightArmPivot.rotation.x = -Math.PI / 2.3 + Math.cos(typeSpeed) * 0.12;
        leftArmPivot.rotation.z = 0.2;
        rightArmPivot.rotation.z = -0.2;
      } else if (hasDialogue) {
        // Gesturing while seated speaking
        leftArmPivot.rotation.x = -0.5 + Math.sin(time * 4) * 0.25;
        rightArmPivot.rotation.x = -0.5 + Math.cos(time * 4) * 0.25;
        leftArmPivot.rotation.z = 0.2;
        rightArmPivot.rotation.z = -0.2;
      } else {
        // Resting hands naturally on desk or chair armrests
        leftArmPivot.rotation.x = -0.45;
        rightArmPivot.rotation.x = -0.45;
        leftArmPivot.rotation.z = 0.15;
        rightArmPivot.rotation.z = -0.15;
      }

      if (head) {
        if (isWorking) {
          head.rotation.x = 0.15 + Math.sin(time * 3) * 0.05;
          head.rotation.y = Math.sin(time * 1.5) * 0.08;
        } else {
          head.rotation.x = 0.05;
          head.rotation.y = Math.sin(time * 1.2) * 0.15;
        }
      }
    } else {
      // Standing idle at designated zone (Coffee Stand, Server, Arcade, Whiteboard)
      const breathe = Math.sin(time * 2.5);
      body.position.y = breathe * 0.015;

      if (hasDialogue) {
        // Gesture with hands while speaking
        leftArmPivot.rotation.x = -0.4 + Math.sin(time * 4) * 0.3;
        rightArmPivot.rotation.x = -0.4 + Math.cos(time * 4) * 0.3;
        leftArmPivot.rotation.z = 0.25;
        rightArmPivot.rotation.z = -0.25;
      } else if (idleState === 'ARCADE') {
        // Playing retro arcade: joystick movements and button tapping
        leftArmPivot.rotation.x = -Math.PI / 2.7 + Math.sin(time * 10) * 0.12;
        rightArmPivot.rotation.x = -Math.PI / 2.7 + Math.cos(time * 14) * 0.15;
        leftArmPivot.rotation.z = 0.15;
        rightArmPivot.rotation.z = -0.15;
      } else if (idleState === 'WHITEBOARD') {
        // Pondering with hand on chin
        leftArmPivot.rotation.x = -Math.PI / 2.1;
        rightArmPivot.rotation.x = -0.2;
        leftArmPivot.rotation.z = 0.2;
        rightArmPivot.rotation.z = -0.1;
      } else if (idleState === 'BREAK' || idleState === 'Coffee Stand') {
        // Holding and sipping coffee
        leftArmPivot.rotation.x = -Math.PI / 2.6 + Math.sin(time * 2) * 0.08;
        rightArmPivot.rotation.x = -0.3;
        leftArmPivot.rotation.z = 0.2;
        rightArmPivot.rotation.z = -0.1;
      } else {
        leftArmPivot.rotation.x = breathe * 0.06;
        rightArmPivot.rotation.x = -breathe * 0.06;
        leftArmPivot.rotation.z = 0.08;
        rightArmPivot.rotation.z = -0.08;
      }

      if (head) {
        head.rotation.x = 0;
        head.rotation.y = Math.sin(time * 1.2) * 0.15;
      }
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // 2D PROJECTED SCREEN OVERLAYS (Speech bubbles & nametags follow 3D agents)
  // ═══════════════════════════════════════════════════════════════════════════
  public getScreenOverlays(): ScreenOverlayPos[] {
    if (!this.canvas) return [];

    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    const overlays: ScreenOverlayPos[] = [];
    const tempV = new THREE.Vector3();

    this.agentMeshes.forEach((agentGroup, agentId) => {
      agentGroup.getWorldPosition(tempV);
      tempV.y += 2.25; // point directly above character head

      tempV.project(this.camera);

      // Check if inside camera view frustum (z < 1)
      const visible = tempV.z < 1 && tempV.x >= -1.2 && tempV.x <= 1.2 && tempV.y >= -1.2 && tempV.y <= 1.2;

      const screenX = (tempV.x * 0.5 + 0.5) * width;
      const screenY = (-tempV.y * 0.5 + 0.5) * height;

      overlays.push({
        agentId,
        x: screenX,
        y: screenY,
        visible
      });
    });

    return overlays;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // CAMERA PRESETS & TRANSITIONS
  // ═══════════════════════════════════════════════════════════════════════════
  public setCameraPreset(mode: 'iso' | 'cinematic' | 'topdown' | 'warroom' | 'lounge'): void {
    let targetCamPos: THREE.Vector3;
    let targetLookAt: THREE.Vector3;

    switch (mode) {
      case 'iso':
        targetCamPos = new THREE.Vector3(22, 19, 22);
        targetLookAt = new THREE.Vector3(1.5, 0, 0);
        break;
      case 'cinematic':
        targetCamPos = new THREE.Vector3(14, 8, 14);
        targetLookAt = new THREE.Vector3(-1, 1, 0);
        break;
      case 'topdown':
        targetCamPos = new THREE.Vector3(0.1, 34, 0.1);
        targetLookAt = new THREE.Vector3(0, 0, 0);
        break;
      case 'warroom':
        targetCamPos = new THREE.Vector3(0, 7.5, 7.5);
        targetLookAt = new THREE.Vector3(0, 1.2, 0);
        break;
      case 'lounge':
        targetCamPos = new THREE.Vector3(-6, 7, -2);
        targetLookAt = new THREE.Vector3(-10.5, 1, -6.5);
        break;
    }

    this.flyCamera(targetCamPos, targetLookAt);
  }

  public focusAgent(agentId: string): void {
    this.selectedAgentId = agentId;

    // Update selection rings
    this.agentMeshes.forEach((mesh, id) => {
      const ring = mesh.getObjectByName('selectionRing');
      if (ring) ring.visible = id === agentId;
    });

    const agentGroup = this.agentMeshes.get(agentId);
    if (!agentGroup) return;

    const pos = agentGroup.position;
    const targetCamPos = new THREE.Vector3(pos.x + 5.5, pos.y + 4.5, pos.z + 5.5);
    const targetLookAt = new THREE.Vector3(pos.x, pos.y + 1.2, pos.z);

    this.flyCamera(targetCamPos, targetLookAt);
  }

  private flyCamera(endPos: THREE.Vector3, endTarget: THREE.Vector3): void {
    this.camStartPos.copy(this.camera.position);
    this.camEndPos.copy(endPos);
    this.targetStartPos.copy(this.controls.target);
    this.targetEndPos.copy(endTarget);
    this.camTransitionProgress = 0;
    this.isCameraTransitioning = true;
  }

  private easeInOutQuad(t: number): number {
    return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // INTERACTION / RAYCASTING
  // ═══════════════════════════════════════════════════════════════════════════
  private onPointerClick(e: MouseEvent): void {
    const rect = this.canvas.getBoundingClientRect();
    this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.mouse, this.camera);
    const intersects = this.raycaster.intersectObjects(this.scene.children, true);

    for (const hit of intersects) {
      let cur: THREE.Object3D | null = hit.object;
      while (cur && cur !== this.scene) {
        if (cur.userData?.['isAgent'] && cur.userData?.['agentId']) {
          const agentId = cur.userData['agentId'];
          this.focusAgent(agentId);
          if (this.onAgentClickCb) this.onAgentClickCb(agentId);
          return;
        }
        if (cur.userData?.['isDesk'] && cur.userData?.['agentId']) {
          const agentId = cur.userData['agentId'];
          this.focusAgent(agentId);
          if (this.onAgentClickCb) this.onAgentClickCb(agentId);
          return;
        }
        cur = cur.parent;
      }
    }
  }

  private onPointerMove(e: MouseEvent): void {
    const rect = this.canvas.getBoundingClientRect();
    this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.mouse, this.camera);
    const intersects = this.raycaster.intersectObjects(this.scene.children, true);

    let foundAgent = false;
    for (const hit of intersects) {
      let cur: THREE.Object3D | null = hit.object;
      while (cur && cur !== this.scene) {
        if (cur.userData?.['isAgent'] || cur.userData?.['isDesk']) {
          foundAgent = true;
          break;
        }
        cur = cur.parent;
      }
      if (foundAgent) break;
    }

    this.canvas.style.cursor = foundAgent ? 'pointer' : 'default';
  }

  private onResize(): void {
    if (!this.container || !this.renderer || !this.camera) return;
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    if (width === 0 || height === 0) return;

    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  public destroy(): void {
    if (this.reqId) cancelAnimationFrame(this.reqId);
    if (this.resizeObserver) this.resizeObserver.disconnect();
    this.controls?.dispose();
    this.renderer?.dispose();
  }
}

