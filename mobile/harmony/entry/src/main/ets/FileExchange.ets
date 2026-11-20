import { fileIo as fs, picker } from '@kit.CoreFileKit';
import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';

export class FileExchange {
  private file?: fs.File;
  private temp: string = '';
  private target: string = '';
  private generation: number = 0;
  private choosing: boolean = false;

  async upload(context: common.UIAbilityContext, event: OnShowFileSelectorEvent): Promise<void> {
    const epoch = this.generation;
    try {
      const options = new picker.DocumentSelectOptions();
      options.maxSelectNumber = event.fileSelector.getMode() === FileSelectorMode.FileOpenMultipleMode ? 32 : 1;
      const chosen = await new picker.DocumentViewPicker(context).select(options);
      event.result.handleFileList(epoch === this.generation ? chosen : []);
    } catch { event.result.handleFileList([]); }
  }

  async handle(context: common.UIAbilityContext, op: string, value: string): Promise<string> {
    const epoch = this.generation;
    try {
      if (op === 'choose') {
        if (this.choosing || this.file || !value || value.length > 255 || /[/\\]/.test(value)) return 'error';
        this.choosing = true;
        const options = new picker.DocumentSaveOptions();
        options.newFileNames = [value];
        let choices: string[];
        try { choices = await new picker.DocumentViewPicker(context).save(options); }
        finally { if (epoch === this.generation) this.choosing = false; }
        if (!choices.length || epoch !== this.generation) return 'cancel';
        this.target = choices[0];
        this.temp = context.cacheDir + '/focus-save-' + util.generateRandomUUID() + '.part';
        this.file = fs.openSync(this.temp, fs.OpenMode.CREATE | fs.OpenMode.READ_WRITE);
        return 'ok';
      }
      if (op === 'abort') { this.cancel(); return 'ok'; }
      if (!this.file) return 'error';
      if (op === 'write' && value.length <= 32768) {
        const bytes = new util.Base64Helper().decodeSync(value);
        const data = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
        if (await fs.write(this.file.fd, data) !== bytes.byteLength) throw new Error('Short write');
        return epoch === this.generation ? 'ok' : 'error';
      }
      if (op === 'finish') {
        fs.closeSync(this.file); this.file = undefined;
        const input = fs.openSync(this.temp, fs.OpenMode.READ_ONLY);
        try {
          const output = fs.openSync(this.target, fs.OpenMode.WRITE_ONLY | fs.OpenMode.TRUNC);
          try { await fs.copyFile(input.fd, output.fd); }
          finally { fs.closeSync(output); }
        } finally { fs.closeSync(input); }
        if (epoch !== this.generation) return 'error';
        this.cancel();
        return 'ok';
      }
    } catch { if (epoch === this.generation) this.cancel(); }
    return 'error';
  }

  cancel(): void {
    this.generation++;
    this.choosing = false;
    if (this.file) { fs.closeSync(this.file); this.file = undefined; }
    if (this.temp) { try { fs.unlinkSync(this.temp); } catch {} }
    this.temp = ''; this.target = '';
  }
}
