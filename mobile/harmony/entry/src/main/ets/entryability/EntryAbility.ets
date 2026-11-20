import { AbilityConstant, UIAbility } from '@kit.AbilityKit';
import { window } from '@kit.ArkUI';

export default class EntryAbility extends UIAbility {
  onWindowStageCreate(stage: window.WindowStage): void {
    stage.loadContent('pages/Index');
  }
  onMemoryLevel(level: AbilityConstant.MemoryLevel): void {
    AppStorage.setOrCreate('focusMemoryWarning', (AppStorage.get<number>('focusMemoryWarning') ?? 0) + 1);
  }
  onForeground(): void { AppStorage.setOrCreate('focusForeground', true); }
  onBackground(): void { AppStorage.setOrCreate('focusForeground', false); }
}
