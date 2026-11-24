import { request } from './client'
import type {
  ActionResult,
  DispositionPage,
  DispositionSnapshot,
} from '@/data/types'

export type DispositionScope = 'open' | 'unclaimed' | 'claimed' | 'reviewed' | 'all'

/** 错误处置差异视图：按追踪号列出详情状态与旧处理字段对不上的错误。 */
export async function listDispositions(
  scope: DispositionScope = 'open',
  keyword = '',
): Promise<DispositionPage> {
  const query = new URLSearchParams({ scope })
  if (keyword.trim()) query.set('keyword', keyword.trim())
  const response = await request(`/api/error-dispositions?${query.toString()}`)
  if (!response.ok) throw new Error('错误处置差异视图读取失败')
  return await response.json()
}

/** 运营概览复核明细：待复核统计与待领列表来自后端同一次实时计算。 */
export async function fetchDispositionSnapshot(): Promise<DispositionSnapshot> {
  const response = await request('/api/error-dispositions/snapshot')
  if (!response.ok) throw new Error('错误处置复核明细读取失败')
  return await response.json()
}

/** 值班员按追踪号领取差异；并发领取时后端保证只有一人成功。 */
export async function claimDisposition(traceId: string, operator: string): Promise<ActionResult> {
  const response = await request(`/api/error-dispositions/${encodeURIComponent(traceId)}/claim`, {
    method: 'POST',
    body: JSON.stringify({ operator }),
  })
  return await response.json()
}

/** 归属值班员完成复核；后端只更新复核表，不重新触发实际错误处理。 */
export async function reviewDisposition(
  traceId: string,
  operator: string,
  remark = '',
): Promise<ActionResult> {
  const response = await request(`/api/error-dispositions/${encodeURIComponent(traceId)}/review`, {
    method: 'POST',
    body: JSON.stringify({ operator, remark }),
  })
  return await response.json()
}
