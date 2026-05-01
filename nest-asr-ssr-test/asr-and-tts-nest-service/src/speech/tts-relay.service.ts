import { Inject, Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { createHmac, randomUUID } from 'node:crypto';
import { OnEvent } from '@nestjs/event-emitter';
import { AI_TTS_STREAM_EVENT, type AiTtsStreamEvent } from '../common/stream-events';
import WebSocket from 'ws';

type ClientSession = {
  sessionId: string;
  clientWs: WebSocket;
  tencentWs?: WebSocket;
  ready: boolean;
  pendingChunks: string[];
  closed: boolean;
};

@Injectable()
export class TtsRelayService implements OnModuleDestroy {
  private readonly logger = new Logger(TtsRelayService.name);
  private readonly sessions = new Map<string, ClientSession>();
  private readonly secretId: string;
  private readonly secretKey: string;
  private readonly appId: number;
  private readonly voiceType: number;

  constructor(@Inject(ConfigService) configService: ConfigService) {
    this.secretId = configService.get<string>('SECRET_ID') ?? '';
    this.secretKey = configService.get<string>('SECRET_KEY') ?? '';
    this.appId = Number(configService.get<string>('APP_ID') ?? 0);
    this.voiceType = Number(configService.get<string>('TTS_VOICE_TYPE') ?? 101001);
  }

  onModuleDestroy(): void {
    for (const session of this.sessions.values()) {
      this.closeSession(session.sessionId, 'module destroy');
    }
  }

  // 注册新的 TTS 客户端连接，生成或使用提供的会话 ID，创建会话对象并存储在会话管理中，同时向客户端发送包含会话 ID 的 JSON 消息确认连接成功，并记录日志说明新客户端已连接
  registerClient(clientWs: WebSocket, wantedSessionId?: string): string {

    const sessionId = wantedSessionId?.trim() || randomUUID();
    const existing = this.sessions.get(sessionId);

    if (existing) {
      this.closeSession(sessionId, 'client reconnected');
    }

    // 创建新的会话对象，包含会话 ID、客户端 WebSocket 连接、连接状态和待发送的文本块队列，并将其存储在会话管理中以便后续处理 TTS 流式数据的转发和连接管理
    this.sessions.set(sessionId, {
      sessionId,
      clientWs,
      ready: false,
      pendingChunks: [],
      closed: false,
    });

    this.sendClientJson(clientWs, { type: 'session', sessionId });
    this.logger.log(`TTS client connected: ${sessionId}`);
    return sessionId;
  }

  unregisterClient(sessionId: string): void {
    this.closeSession(sessionId, 'client disconnected');
  }

  //监听 AI_TTS_STREAM_EVENT 事件，根据事件类型处理 TTS 流式数据的转发和错误处理逻辑，确保将 AI 生成的 TTS 文本块正确地发送到腾讯云 TTS 服务，并将服务返回的音频数据流转发给前端客户端进行播放，同时处理连接状态和错误情况，维护会话的正常运行
  @OnEvent(AI_TTS_STREAM_EVENT)
  handleAiStreamEvent(event: AiTtsStreamEvent): void {
    const session = this.sessions.get(event.sessionId);
    if (!session) return;

    switch (event.type) {
      // 当接收到 TTS 流开始事件时，确保与腾讯云 TTS 的 WebSocket 连接已建立，如果尚未建立则创建连接，并向客户端发送包含会话 ID 和查询内容的 JSON 消息，通知客户端 TTS 流已开始
      case 'start': {
        this.ensureTencentConnection(session);
        this.sendClientJson(session.clientWs, {
          type: 'tts_started',
          sessionId: session.sessionId,
          query: event.query,
        });
        break;
      }

      // 当接收到 TTS 流文本块事件时，首先检查文本块内容是否有效，如果无效则忽略该事件；如果有效则检查与腾讯云 TTS 的连接状态，
      //如果连接尚未准备好则将文本块保存在会话的 pendingChunks 队列中，等待连接建立后再发送；如果连接已准备好则直接将文本块发送到腾讯云 TTS WebSocket 进行语音合成
      case 'chunk': {
        const chunk = event.chunk?.trim();

        if (!chunk) return;


        if (!session.ready || !session.tencentWs || session.tencentWs.readyState !== WebSocket.OPEN) {
          session.pendingChunks.push(chunk);
          return;
        }

        this.sendTencentChunk(session, chunk);

        break;
      }

      // 当接收到 TTS 流结束事件时，首先调用 flushPendingChunks 方法确保所有待发送的文本块都已发送到腾讯云 TTS，然后如果与腾讯云 TTS 的连接仍然处于 OPEN 状态则发送一个包含会话 ID 和完成动作的 JSON 消息通知腾讯云 TTS 流已完成，最后等待腾讯云 TTS 发送完所有音频数据后由客户端触发连接关闭
      case 'end': {
        this.flushPendingChunks(session);
        if (session.tencentWs && session.tencentWs.readyState === WebSocket.OPEN) {
          session.tencentWs.send(
            JSON.stringify({
              session_id: session.sessionId,
              action: 'ACTION_COMPLETE',
            }),
          );
        }
        break;
      }
      case 'error': {
        this.sendClientJson(session.clientWs, {
          type: 'tts_error',
          message: event.error,
        });
        this.closeSession(session.sessionId, 'ai stream error');
        break;
      }
    }
  }

  // 确保与腾讯云 TTS 的 WebSocket 连接已建立，如果尚未建立则创建连接，并设置相应的事件处理逻辑来转发数据和处理错误
  private ensureTencentConnection(session: ClientSession): void {
    if (session.tencentWs && session.tencentWs.readyState <= WebSocket.OPEN) {
      return;
    }
    if (!this.secretId || !this.secretKey || !this.appId) {
      this.sendClientJson(session.clientWs, {
        type: 'tts_error',
        message: 'TTS 凭证缺失，请检查 SECRET_ID/SECRET_KEY/APP_ID',
      });
      return;
    }

    const url = this.buildTencentTtsWsUrl(session.sessionId);
    const tencentWs = new WebSocket(url);
    session.tencentWs = tencentWs;
    session.ready = false;

    tencentWs.on('open', () => {
      this.logger.log(`Tencent TTS ws opened: ${session.sessionId}`);
    });

    tencentWs.on('message', (data, isBinary) => {
      if (session.closed) return;
      if (isBinary) {
        if (session.clientWs.readyState === WebSocket.OPEN) {
          session.clientWs.send(data, { binary: true });
        }
        return;
      }

      const raw = data.toString();
      let msg: Record<string, unknown> | undefined;
      try {
        msg = JSON.parse(raw) as Record<string, unknown>;
      } catch {
        return;
      }

      if (Number(msg.ready) === 1) {
        session.ready = true;
        this.flushPendingChunks(session);
      }

      if (Number(msg.code) && Number(msg.code) !== 0) {
        this.sendClientJson(session.clientWs, {
          type: 'tts_error',
          message: String(msg.message ?? 'Tencent TTS error'),
          code: Number(msg.code),
        });
        this.closeSession(session.sessionId, 'tencent error');
        return;
      }

      if (Number(msg.final) === 1) {
        this.sendClientJson(session.clientWs, { type: 'tts_final' });
      }
    });

    tencentWs.on('error', (error) => {
      this.sendClientJson(session.clientWs, {
        type: 'tts_error',
        message: `Tencent ws error: ${error.message}`,
      });
    });

    tencentWs.on('close', () => {
      session.tencentWs = undefined;
      session.ready = false;
    });
  }

  // 将所有待发送的 TTS 文本块发送到腾讯云 TTS WebSocket，如果连接尚未准备好则将文本块保存在会话的 pendingChunks 队列中，等待连接建立后再发送
  private flushPendingChunks(session: ClientSession): void {
    if (!session.ready || !session.tencentWs || session.tencentWs.readyState !== WebSocket.OPEN) {
      return;
    }
    while (session.pendingChunks.length > 0) {
      const chunk = session.pendingChunks.shift();
      if (!chunk) continue;
      this.sendTencentChunk(session, chunk);
    }
  }

  // 发送单个文本块到腾讯云 TTS WebSocket，如果连接尚未准备好则将文本块保存在会话的 pendingChunks 队列中，等待连接建立后再发送
  private sendTencentChunk(session: ClientSession, text: string): void {
    
    if (!session.tencentWs || session.tencentWs.readyState !== WebSocket.OPEN) {
      session.pendingChunks.push(text);
      return;
    }

    session.tencentWs.send(
      JSON.stringify({
        session_id: session.sessionId,
        message_id: `msg_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        action: 'ACTION_SYNTHESIS',
        data: text,
      }),
    );
  }

  // 关闭指定会话的连接，首先标记会话为已关闭状态，然后依次关闭与腾讯云 TTS 的 WebSocket 连接和客户端的 WebSocket 连接，并从会话管理中删除该会话，最后记录日志说明会话已关闭及原因
  private closeSession(sessionId: string, reason: string): void {
    const session = this.sessions.get(sessionId);
    if (!session) return;
    session.closed = true;

    if (session.tencentWs && session.tencentWs.readyState < WebSocket.CLOSING) {
      session.tencentWs.close();
    }
    if (session.clientWs.readyState < WebSocket.CLOSING) {
      this.sendClientJson(session.clientWs, { type: 'tts_closed', reason });
      session.clientWs.close();
    }
    this.sessions.delete(sessionId);
    this.logger.log(`TTS session closed: ${sessionId}, reason: ${reason}`);
  }

  // 向客户端 WebSocket 连接发送 JSON 格式的消息，首先检查连接是否处于 OPEN 状态，如果是则将消息对象转换为 JSON 字符串并通过 WebSocket 发送给客户端
  private sendClientJson(clientWs: WebSocket, payload: Record<string, unknown>): void {
    if (clientWs.readyState !== WebSocket.OPEN) return;
    clientWs.send(JSON.stringify(payload));
  }

  // 构建腾讯云 TTS WebSocket 的连接 URL，使用当前时间戳和 TTS 请求参数生成签名字符串，并将签名和参数一起构建成完整的 WebSocket URL，供客户端连接腾讯云 TTS 服务时使用
  private buildTencentTtsWsUrl(sessionId: string): string {
    const now = Math.floor(Date.now() / 1000);
    const params: Record<string, string | number> = {
      Action: 'TextToStreamAudioWSv2',
      AppId: this.appId,
      Codec: 'mp3',
      Expired: now + 3600,
      SampleRate: 16000,
      SecretId: this.secretId,
      SessionId: sessionId,
      Speed: 0,
      Timestamp: now,
      VoiceType: this.voiceType,
      Volume: 5,
    };

    const signStr = Object.keys(params)
      .sort()
      .map((k) => `${k}=${params[k]}`)
      .join('&');
    const rawStr = `GETtts.cloud.tencent.com/stream_wsv2?${signStr}`;
    const signature = createHmac('sha1', this.secretKey).update(rawStr).digest('base64');
    const searchParams = new URLSearchParams({
      ...Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)])),
      Signature: signature,
    });

    return `wss://tts.cloud.tencent.com/stream_wsv2?${searchParams.toString()}`;
  }
}