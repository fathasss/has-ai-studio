import { Pipe, PipeTransform } from '@angular/core';
import { I18nService } from '../services/i18n.service';

@Pipe({
  name: 'translate',
  standalone: true,
  pure: false // ensures live re-rendering when language switches without page refresh
})
export class TranslatePipe implements PipeTransform {
  constructor(private i18nService: I18nService) {}

  transform(key: string, params?: Record<string, string | number>): string {
    return this.i18nService.t(key, params);
  }
}

