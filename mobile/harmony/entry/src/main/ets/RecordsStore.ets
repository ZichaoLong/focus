import { relationalStore } from '@kit.ArkData';
import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';

let opening: Promise<relationalStore.RdbStore> | undefined;
let commands: Record<string,string[]> = {};

async function open(ctx: common.UIAbilityContext): Promise<relationalStore.RdbStore> {
  const bytes = ctx.resourceManager.getRawFileContentSync('records-sql.json');
  commands = JSON.parse(util.TextDecoder.create('utf-8').decodeToString(bytes)) as Record<string,string[]>;
  const db = await relationalStore.getRdbStore(ctx,{name:'offline-records-v1.db',encrypt:true,securityLevel:relationalStore.SecurityLevel.S3});
  for (const sql of commands['schema']) await db.executeSql(sql);
  return db;
}

function steps(db: relationalStore.RdbStore, op: string, data: Record<string,string>, rows: Record<string,string>[]): void {
  for (const template of commands[op]) {
    if (template.startsWith('@')) { steps(db,template.substring(1),data,rows); continue; }
    const guard = template.startsWith('!'), read = template.startsWith('?');
    const statement = guard || read ? template.substring(1) : template;
    const args: string[] = [];
    const sql = statement.replace(/:([a-z]+)/g, (match: string, key: string): string => {
      if (data[key] === undefined) throw new Error('缺少记录字段');
      args.push(String(data[key])); return '?';
    });
    if (!guard && !read) { db.executeSync(sql,args); continue; }
    const cursor = db.querySqlSync(sql,args);
    try {
      if (guard && !cursor.goToFirstRow()) throw new Error('记录已变更或空间已满');
      while (read && cursor.goToNextRow()) {
        const row: Record<string,string> = {};
        cursor.columnNames.forEach((name: string, i: number) => { row[name] = cursor.getString(i); });
        rows.push(row);
      }
    } finally { cursor.close(); }
  }
}

export async function recordCall(ctx: common.UIAbilityContext, id: string, origin: string, op: string,
  data: Record<string,string>, current: () => boolean = () => true): Promise<string> {
  if (!opening) opening = open(ctx).catch((error: Error) => { opening=undefined; throw error; });
  const db = await opening;
  if (!current()) throw new Error('页面已切换');
  data['site'] = id + '|' + origin;
  const rows: Record<string,string>[] = [];
  db.beginTransaction();
  try {
    steps(db,op,data,rows); db.commit();
  } catch (error) { db.rollBack(); throw error as Error; }
  return JSON.stringify(rows);
}

export function recordAllowed(local: boolean, op: string): boolean {
  const list = local ? ' status enable list book chunk bookmark touch candidates cleanselected allow ' :
    ' auth lock revoke note touch capture checkpoint start write finish live bookmark closed revert allow ';
  return /^[a-z]+$/.test(op) && list.includes(' '+op+' ');
}
