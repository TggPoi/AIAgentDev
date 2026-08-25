import {
  apiErrorFromResponse,
  networkApiError,
  protocolApiError,
} from '@/api/api-error'
import {
  isEventStreamMediaType,
  isJsonMediaType,
  isTextMediaType,
} from '@/api/media-type'

export type ApiResponseType = 'blob' | 'empty' | 'json' | 'text'

export interface ApiRequestOptions
  extends Omit<RequestInit, 'body' | 'headers'> {
  authenticated?: boolean
  body?: BodyInit | null
  headers?: HeadersInit
  json?: unknown
  requestId?: string
  responseType?: ApiResponseType
  retryOnUnauthorized?: boolean
}

export interface ApiResponse<T> {
  data: T
  headers: Headers
  requestId: string
  status: number
}

export interface ApiStreamResponse {
  body: ReadableStream<Uint8Array>
  headers: Headers
  requestId: string
  status: number
}

export interface HttpClientOptions {
  baseUrl: string
  fetchImpl?: typeof fetch
  getAccessToken: () => string | null
  refreshAccessToken?: () => Promise<void>
  requestIdFactory?: () => string
}

export interface HttpClient {
  openEventStream(
    path: string,
    options?: ApiRequestOptions,
  ): Promise<ApiStreamResponse>
  request<T = unknown>(
    path: string,
    options?: ApiRequestOptions,
  ): Promise<ApiResponse<T>>
}

function normalizeBaseUrl(value: string): string {
  const url = new URL(value)
  if (
    (url.protocol !== 'http:' && url.protocol !== 'https:') ||
    url.username.length > 0 ||
    url.password.length > 0 ||
    url.search.length > 0 ||
    url.hash.length > 0
  ) {
    throw new Error('API base URL must be a credential-free HTTP(S) URL')
  }
  return value.replace(/\/+$/, '')
}

function resolveApiUrl(baseUrl: string, path: string): string {
  if (!path.startsWith('/') || path.startsWith('//') || path.includes('\\')) {
    throw new Error('API path must be an internal absolute path')
  }
  return `${baseUrl}${path}`
}

function buildRequestInit(
  options: ApiRequestOptions,
  token: string | null,
  requestId: string,
): RequestInit {
  const {
    authenticated: _authenticated,
    body: explicitBody,
    headers: inputHeaders,
    json,
    requestId: _requestId,
    responseType: _responseType,
    retryOnUnauthorized: _retryOnUnauthorized,
    ...requestInit
  } = options
  const headers = new Headers(inputHeaders)

  headers.set('X-Request-ID', requestId)
  if (token === null) {
    headers.delete('Authorization')
  } else {
    headers.set('Authorization', `Bearer ${token}`)
  }

  let body = explicitBody
  if (json !== undefined) {
    if (explicitBody !== undefined && explicitBody !== null) {
      throw new Error('Use either json or body, not both')
    }
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(json)
  }

  return {
    ...requestInit,
    body,
    headers,
  }
}

async function parseSuccessResponse(
  response: Response,
  responseType: ApiResponseType,
  requestId: string,
): Promise<unknown> {
  if (response.status === 204 || responseType === 'empty') {
    return undefined
  }

  const contentType = response.headers.get('Content-Type')
  switch (responseType) {
    case 'blob':
      return response.blob()
    case 'json':
      if (!isJsonMediaType(contentType)) {
        throw protocolApiError({
          code: 'UNEXPECTED_CONTENT_TYPE',
          message: '服务端返回了非 JSON 响应',
          requestId,
          status: response.status,
        })
      }
      try {
        return await response.json()
      } catch {
        throw protocolApiError({
          code: 'INVALID_JSON_RESPONSE',
          message: '服务端返回了无法解析的 JSON',
          requestId,
          status: response.status,
        })
      }
    case 'text':
      if (!isTextMediaType(contentType)) {
        throw protocolApiError({
          code: 'UNEXPECTED_CONTENT_TYPE',
          message: '服务端返回了非文本响应',
          requestId,
          status: response.status,
        })
      }
      return response.text()
  }
}

export function createHttpClient(options: HttpClientOptions): HttpClient {
  const baseUrl = normalizeBaseUrl(options.baseUrl)
  const fetchImpl = options.fetchImpl ?? fetch
  const requestIdFactory = options.requestIdFactory ?? (() => crypto.randomUUID())
  let refreshPromise: Promise<void> | null = null

  function refreshAccessToken(): Promise<void> {
    if (refreshPromise !== null) {
      return refreshPromise
    }
    if (options.refreshAccessToken === undefined) {
      return Promise.reject(new Error('No access-token refresh callback configured'))
    }

    refreshPromise = Promise.resolve()
      .then(options.refreshAccessToken)
      .finally(() => {
        refreshPromise = null
      })
    return refreshPromise
  }

  async function execute(
    path: string,
    requestOptions: ApiRequestOptions = {},
  ): Promise<{ requestId: string; response: Response }> {
    const requestId = requestOptions.requestId ?? requestIdFactory()
    const send = async (): Promise<Response> => {
      const token =
        requestOptions.authenticated === false ? null : options.getAccessToken()
      try {
        return await fetchImpl(
          resolveApiUrl(baseUrl, path),
          buildRequestInit(requestOptions, token, requestId),
        )
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') {
          throw error
        }
        throw networkApiError(requestId)
      }
    }

    let response = await send()
    const canRefresh =
      response.status === 401 &&
      requestOptions.authenticated !== false &&
      requestOptions.retryOnUnauthorized !== false &&
      options.refreshAccessToken !== undefined
    if (canRefresh) {
      await refreshAccessToken()
      response = await send()
    }

    if (!response.ok) {
      throw await apiErrorFromResponse(response, requestId)
    }
    return { requestId, response }
  }

  return {
    async openEventStream(
      path: string,
      requestOptions: ApiRequestOptions = {},
    ) {
      const { requestId, response } = await execute(path, requestOptions)
      const responseRequestId = response.headers.get('X-Request-ID')

      if (responseRequestId !== requestId) {
        throw protocolApiError({
          code: 'RESPONSE_REQUEST_ID_MISMATCH',
          message: '流式响应的请求标识不匹配',
          requestId,
          status: response.status,
        })
      }
      if (!isEventStreamMediaType(response.headers.get('Content-Type'))) {
        throw protocolApiError({
          code: 'UNEXPECTED_CONTENT_TYPE',
          message: '服务端返回了非 SSE 响应',
          requestId,
          status: response.status,
        })
      }
      if (response.body === null) {
        throw protocolApiError({
          code: 'MISSING_STREAM_BODY',
          message: '服务端流式响应缺少消息体',
          requestId,
          status: response.status,
        })
      }

      return {
        body: response.body,
        headers: response.headers,
        requestId,
        status: response.status,
      }
    },

    async request<T>(
      path: string,
      requestOptions: ApiRequestOptions = {},
    ) {
      const { requestId, response } = await execute(path, requestOptions)
      const responseRequestId = response.headers.get('X-Request-ID') ?? requestId
      const data = await parseSuccessResponse(
        response,
        requestOptions.responseType ?? 'json',
        responseRequestId,
      )

      return {
        data: data as T,
        headers: response.headers,
        requestId: responseRequestId,
        status: response.status,
      }
    },
  }
}
