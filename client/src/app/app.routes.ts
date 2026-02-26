import { Routes } from '@angular/router';
import { DashboardComponent } from './features/dashboard/dashboard.component';
import { SettingsComponent } from './features/settings/settings.component';
import { ActiveProjectsComponent } from './features/active-projects/active-projects.component';
import { ExecutionTracesComponent } from './features/execution-traces/execution-traces.component';
import { ProjectsComponent } from './features/projects/projects.component';
import { ExceptionsComponent } from './features/exceptions/exceptions.component';
import { ReportsComponent } from './features/reports/reports.component';

export const routes: Routes = [
  { path: '', redirectTo: '/dashboard', pathMatch: 'full' },
  { path: 'dashboard', component: DashboardComponent },
  { path: 'active-projects', component: ActiveProjectsComponent },
  { path: 'projects', component: ProjectsComponent },
  { path: 'reports', component: ReportsComponent },
  { path: 'execution-traces', component: ExecutionTracesComponent },
  { path: 'exceptions', component: ExceptionsComponent },
  { path: 'settings', component: SettingsComponent },
  { path: '**', redirectTo: '/dashboard' }
];
