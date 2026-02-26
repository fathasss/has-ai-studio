import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { OrchestratorService } from '../../services/orchestrator.service';
import hljs from 'highlight.js';

export interface FileNode {
  name: string;
  path: string;
  isDirectory: boolean;
  children: FileNode[];
  expanded: boolean;
}

@Component({
  selector: 'app-projects',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './projects.component.html',
  styleUrls: ['./projects.component.scss']
})
export class ProjectsComponent implements OnInit {
  projects: string[] = [];
  searchQuery: string = '';
  expandedProjects: Set<string> = new Set();
  projectTrees: { [key: string]: FileNode[] } = {};
  selectedProject: string | null = null;
  files: string[] = [];
  fileTree: FileNode[] = [];
  selectedFile: string | null = null;
  fileContent: string | null = null;
  highlightedContent: string | null = null;
  loading: boolean = false;

  constructor(private orchestratorService: OrchestratorService) {}

  ngOnInit(): void {
    this.loadProjects();
  }

  get filteredProjects(): string[] {
    if (!this.searchQuery.trim()) {
      return this.projects;
    }
    const query = this.searchQuery.toLowerCase();
    return this.projects.filter(p => p.toLowerCase().includes(query));
  }

  loadProjects(): void {
    this.loading = true;
    this.orchestratorService.getProjects().subscribe({
      next: (res) => {
        this.projects = res.projects;
        this.loading = false;
        // Optionally auto-expand first project if available
        if (this.projects.length > 0 && this.expandedProjects.size === 0) {
          this.toggleProject(this.projects[0]);
        }
      },
      error: (err) => {
        console.error('Error loading projects', err);
        this.loading = false;
      }
    });
  }

  toggleProject(projectName: string): void {
    if (this.expandedProjects.has(projectName)) {
      this.expandedProjects.delete(projectName);
    } else {
      this.expandedProjects.add(projectName);
      if (!this.projectTrees[projectName]) {
        this.loadProjectFiles(projectName);
      }
    }
  }

  isProjectExpanded(projectName: string): boolean {
    return this.expandedProjects.has(projectName);
  }

  loadProjectFiles(projectName: string): void {
    this.loading = true;
    this.orchestratorService.getProjectFiles(projectName).subscribe({
      next: (res) => {
        this.projectTrees[projectName] = this.buildFileTree(res.files);
        this.loading = false;
      },
      error: (err) => {
        console.error('Error loading files', err);
        this.loading = false;
      }
    });
  }

  toggleNode(node: FileNode, projectName: string, event: Event): void {
    event.stopPropagation();
    if (node.isDirectory) {
      node.expanded = !node.expanded;
    } else {
      this.selectFile(projectName, node.path);
    }
  }

  selectFile(projectName: string, path: string): void {
    this.selectedProject = projectName;
    this.selectedFile = path;
    this.fileContent = null;
    this.loading = true;
    this.orchestratorService.getFileContent(projectName, path).subscribe({
      next: (res) => {
        this.fileContent = res.content;
        this.highlightedContent = this.highlightCode(res.content, path);
        this.loading = false;
      },
      error: (err) => {
        console.error('Error loading file content', err);
        this.loading = false;
      }
    });
  }

  buildFileTree(flatFiles: string[]): FileNode[] {
    const root: FileNode[] = [];
    
    flatFiles.forEach(path => {
      const parts = path.split('/');
      let currentLevel = root;
      
      for (let i = 0; i < parts.length; i++) {
        const part = parts[i];
        const isFile = i === parts.length - 1;
        
        let existingNode = currentLevel.find(n => n.name === part);
        
        if (!existingNode) {
          existingNode = {
            name: part,
            path: parts.slice(0, i + 1).join('/'),
            isDirectory: !isFile,
            children: [],
            expanded: false
          };
          currentLevel.push(existingNode);
        }
        
        currentLevel = existingNode.children;
      }
    });

    const sortNodes = (nodes: FileNode[]) => {
      nodes.sort((a, b) => {
        if (a.isDirectory && !b.isDirectory) return -1;
        if (!a.isDirectory && b.isDirectory) return 1;
        return a.name.localeCompare(b.name);
      });
      nodes.forEach(node => {
        if (node.children.length > 0) {
          sortNodes(node.children);
        }
      });
    };
    sortNodes(root);
    
    return root;
  }

  highlightCode(code: string, path: string): string {
    const extension = path.split('.').pop()?.toLowerCase();
    let language = 'plaintext';
    
    const extMap: {[key: string]: string} = {
      'ts': 'typescript', 'js': 'javascript', 'py': 'python',
      'html': 'xml', 'css': 'css', 'json': 'json', 'md': 'markdown',
      'txt': 'plaintext', 'sh': 'bash', 'yml': 'yaml', 'yaml': 'yaml'
    };
    
    if (extension && extMap[extension]) {
      language = extMap[extension];
    }

    try {
      return hljs.highlight(code, { language }).value;
    } catch (e) {
      return hljs.highlightAuto(code).value;
    }
  }
}
