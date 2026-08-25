import { isJsonMediaType } from '@/api/media-type'

export type ApiErrorStatusKind =
  | 'authentication'
  | 'authorization'
  | 'client'
  | 'conflict'
  | 'network'
  | 'not_found'
  | 'protocol'
  | 'rate_limit'
  | 'server'
  | 'validation'

interface ApiErrorOptions {
  code: string
  errorCategory?: string
  message: string
  requestId: string | null
  retryAfterSeconds?: number
  status: number
  statusKind: ApiErrorStatusKind
  traceId?: string | null
}

export class ApiError extends Error {
  readonly code: string
  readonly errorCategory: string | null
  readonly requestId: string | null
  readonly retryAfterSeconds: number | null
  readonly status: number
  readonly statusKind: ApiErrorStatusKind
  readonly traceId: string | null

  constructor(options: ApiErrorOptions) {
    super(options.message)
    this.name = 'ApiError'
    this.code = options.code
    this.errorCategory = options.errorCategory ?? null
    this.requestId = options.requestId
    this.retryAfterSeconds = options.retryAfterSeconds ?? null
    this.status = options.status
    this.statusKind = options.statusKind
    this.traceId = options.traceId ?? null
  }
}

interface BackendErrorProjection {
  code?: string
  errorCategory?: string
  message?: string
  requestId?: string
  traceId?: string
}

function optionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function projectBackendError(value: unknown): BackendErrorProjection {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return {}
  }

  const record = value as Record<string, unknown>
  return {
    code: optionalString(record.code),
    errorCategory: optionalString(record.error_category),
    message: optionalString(record.message),
    requestId: optionalString(record.request_id),
    traceId: optionalString(record.trace_id),
  }
}

export function statusKindFor(status: number): ApiErrorStatusKind {
  switch (status) {
    case 401:
      return 'authentication'
    case 403:
      return 'authorization'
    case 404:
      return 'not_found'
    case 409:
      return 'conflict'
    case 422:
      return 'validation'
    case 429:
      return 'rate_limit'
    default:
      return status >= 500 ? 'server' : 'client'
  }
}

function defaultMessageFor(status: number): string {
  switch (statusKindFor(status)) {
    case 'authentication':
      return '身份认证已失效'
    case 'authorization':
      return '当前身份无权执行此操作'
    case 'not_found':
      return '资源不存在或当前身份不可访问'
    case 'conflict':
      return '服务端状态已变化，请刷新后重试'
    case 'validation':
      return '请求参数不合法'
    case 'rate_limit':
      return '请求过于频繁，请稍后重试'
    case 'server':
      return '服务暂时不可用'
    default:
      return '请求处理失败'
  }
}

function parseRetryAfter(value: string | null): number | undefined {
  if (value === null || !/^\d+$/.test(value)) {
    return undefined
  }
  const seconds = Number(value)
  return Number.isSafeInteger(seconds) && seconds >= 0 ? seconds : undefined
}

export async function apiErrorFromResponse(
  response: Response,
  fallbackRequestId: string,
): Promise<ApiError> {
  let projection: BackendErrorProjection = {}

  if (isJsonMediaType(response.headers.get('Content-Type'))) {
    try {
      projection = projectBackendError(await response.json())
    } catch {
      projection = {}
    }
  }

  const requestId =
    response.headers.get('X-Request-ID') ??
    projection.requestId ??
    fallbackRequestId

  return new ApiError({
    code: projection.code ?? `HTTP_${response.status}`,
    errorCategory: projection.errorCategory,
    message: projection.message ?? defaultMessageFor(response.status),
    requestId,
    retryAfterSeconds: parseRetryAfter(response.headers.get('Retry-After')),
    status: response.status,
    statusKind: statusKindFor(response.status),
    traceId: projection.traceId,
  })
}

export function protocolApiError(options: {
  code: string
  message: string
  requestId: string
  status: number
}): ApiError {
  return new ApiError({
    ...options,
    statusKind: 'protocol',
  })
}

export function networkApiError(requestId: string): ApiError {
  return new ApiError({
    code: 'NETWORK_ERROR',
    message: '无法连接服务，请检查网络后重试',
    requestId,
    status: 0,
    statusKind: 'network',
  })
}
