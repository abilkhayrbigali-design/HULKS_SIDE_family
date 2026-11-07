import type {Appeal,ChecklistDetail,ChecklistSummary,ChecklistVersion,Conversation,ConversationDetail,Criterion,Decision,Evaluation,ImportSummary,OrganizerRecord,Page} from './types';
const messages:Record<string,string>={AI_NOT_CONFIGURED:'AI ещё не настроен. Добавьте OPENAI_API_KEY в серверный .env и перезапустите сервер. Оценка не создана.',DATASET_NOT_CONFIGURED:'Импорт набора недоступен: серверный адрес источника ещё не настроен.',DATASET_UNAVAILABLE:'Источник данных временно недоступен. Повторите импорт позже.',VALIDATION_ERROR:'Проверьте формат и обязательные поля. Изменения не сохранены.',NOT_FOUND:'Запись не найдена. Обновите список.',CONFLICT:'Данные изменились. Обновите текущую версию перед повтором.',VERSION_CONFLICT:'Версия чек-листа изменилась. Ваши правки сохранены в редакторе.',REVISION_CONFLICT:'Появилось новое решение. Обновите историю перед повтором.',AI_UNAVAILABLE:'AI временно недоступен. Повторите запуск позже.',AI_AUTHENTICATION_ERROR:'Серверу не удалось авторизоваться в AI. Проверьте настройки ключа.',AI_RATE_LIMITED:'Достигнут лимит AI. Подождите и повторите запуск.',NETWORK_ERROR:'Нет соединения с сервером. Проверьте, что он запущен, и повторите действие.',INVALID_RESPONSE:'Сервер вернул неожиданный ответ. Повторите действие.',API_ERROR:'Операция не выполнена. Повторите действие или проверьте сервер.',INTERNAL_ERROR:'Внутренняя ошибка сервера. Изменения не подтверждены.',INTERRUPTED:'Оценка прервана перезапуском сервера. Создайте новый запуск.'};
export const safeCode=(code:unknown)=>typeof code==='string' && Object.hasOwn(messages,code)?code:'API_ERROR';
export const errorMessage=(code:unknown)=>messages[safeCode(code)];
export class ApiError extends Error {status:number;code:string;constructor(status:number,code:unknown){const safe=safeCode(code);super(status===409?messages.CONFLICT:errorMessage(safe));this.status=status;this.code=safe;}}
export function logFailure(status:number,code:unknown){const line=`event=ui_operation_failed status=${status} error=${safeCode(code)}`;if(status>=500||status===0)console.error(line);else console.warn(line);}
export async function request<T>(path:string,options:RequestInit={},quiet=false):Promise<T>{
 try {const response=await fetch(`/api/v1${path}`,{...options,headers:{'Content-Type':'application/json',...options.headers}});if(!response.ok){let code:unknown='API_ERROR';try{code=(await response.json()).error?.code;}catch{/* Use fixed safe fallback. */}throw new ApiError(response.status,code);}try{return await response.json() as T;}catch{throw new ApiError(response.status,'INVALID_RESPONSE');}}
 catch(error){if(error instanceof DOMException&&error.name==='AbortError')throw error;const safe=error instanceof ApiError?error:new ApiError(0,'NETWORK_ERROR');if(!quiet)logFailure(safe.status,safe.code);throw safe;}
}
const post=<T>(path:string,body:unknown)=>request<T>(path,{method:'POST',body:JSON.stringify(body)});
export const api={
 conversations:(query:string)=>request<Page<Conversation>>(`/conversations?${query}`),
 conversation:(id:string,version?:string)=>request<ConversationDetail>(`/conversations/${encodeURIComponent(id)}${version?`?transcript_version_id=${encodeURIComponent(version)}`:''}`),
 importRecords:(records:OrganizerRecord[])=>post<ImportSummary>('/conversations/import',{records}),
 importDataset:(group_id:string)=>post<ImportSummary>('/datasets/import',{group_id}),
 checklists:()=>request<Page<ChecklistSummary>>('/checklists?limit=100'),
 checklist:(id:string)=>request<ChecklistDetail>(`/checklists/${encodeURIComponent(id)}`),
 version:(id:string)=>request<ChecklistVersion>(`/checklist-versions/${encodeURIComponent(id)}`),
 createChecklist:(name:string,criteria:Criterion[])=>post<ChecklistVersion>('/checklists',{name,criteria}),
 saveVersion:(id:string,expected_version_number:number,criteria:Criterion[])=>post<ChecklistVersion>(`/checklists/${encodeURIComponent(id)}/versions`,{expected_version_number,criteria}),
 evaluations:(id:string,offset=0)=>request<Page<Evaluation>>(`/evaluations?conversation_id=${encodeURIComponent(id)}&limit=100&offset=${offset}`),
 evaluation:(id:string,quiet=false)=>request<Evaluation>(`/evaluations/${encodeURIComponent(id)}`,{},quiet),
 evaluate:(conversation_id:string,checklist_version_id:string)=>post<Evaluation>('/evaluations',{conversation_id,checklist_version_id}),
 appeals:(id:string,offset=0)=>request<Page<Appeal>>(`/appeals?evaluation_id=${encodeURIComponent(id)}&limit=100&offset=${offset}`),
 appeal:(id:string,criterion_id:string,comment:string)=>post<Appeal>(`/evaluations/${encodeURIComponent(id)}/appeals`,{criterion_id,comment}),
 decide:(id:string,decision:Decision)=>post<{appeal:Appeal;evaluation:Evaluation}>(`/appeals/${encodeURIComponent(id)}/decisions`,decision),
};
export async function allPages<T>(load:(offset:number)=>Promise<Page<T>>){let result:T[]=[];let offset=0;while(true){const page=await load(offset);result=result.concat(page.items);offset+=page.items.length;if(offset>=page.total||page.items.length===0)return result;}}
